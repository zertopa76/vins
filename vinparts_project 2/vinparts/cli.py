"""Консольный интерфейс.

Примеры:
    python -m vinparts vin WVWZZZAUZFW123456
    python -m vinparts recon
    python -m vinparts index --model "golf 7" --engines
    python -m vinparts docs --model "golf 7" --engine CJSA --op "цепь грм"
    python -m vinparts ask  --model "golf 7" --engine CJSA --op "цепь грм"
    python -m vinparts analyze-file manual.pdf --op "цепь грм"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .extract import ROLE_LABEL_RU, analyze
from .http import HttpError, PoliteClient
from .models import Finding, Vehicle
from .operations import OPERATIONS, Operation, match_operation
from .pipeline import run_query
from .readers import read_file
from .sources import all_adapters, allowed_hosts
from .sources.vwts import BASE_URL, parse_listing
from .store import Store
from .vin import decode

DISCLAIMER = ("Результат получен автоматически из текста руководства и может содержать ошибки. "
              "Перед заказом деталей сверьте его по указанному источнику.")


def _setup_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _client(args, adapters) -> PoliteClient:
    base = config.data_dir(args.data_dir)
    return PoliteClient(base / "cache", allowed_hosts(adapters), min_delay=args.delay,
                        use_cache=not args.no_cache)


def _store(args) -> Store:
    return Store(config.data_dir(args.data_dir) / "index.sqlite")


def _operation(text: str) -> Operation | None:
    op = match_operation(text)
    if op is None:
        print(f"Операция «{text}» не распознана. Доступные операции:")
        for o in OPERATIONS:
            print(f"  - {o.title_ru}")
    return op


def print_findings(op: Operation, vehicle: Vehicle, findings: list[Finding]) -> None:
    print(f"\n{op.title_ru} | {vehicle.describe()}")
    print("=" * 70)
    if not findings:
        print("Пометок о замене сопутствующих деталей в прочитанном тексте не найдено.")
    for f in findings:
        ru = f" - {f.part_ru}" if f.part_ru else ""
        where = f", стр. {f.page}" if f.page else ""
        print(f"\n[{ROLE_LABEL_RU[f.role]}] {f.part}{ru}")
        print(f"   «{f.quote}»")
        print(f"   Источник: {f.source_title}{where} ({f.mentions} упомин.)")
        print(f"   {f.source_url}")
    print("\n" + DISCLAIMER)


# ------------------------------------------------------------------- команды

def cmd_vin(args) -> int:
    info = decode(args.vin)
    if not info.valid_format:
        print(info.note)
        return 1
    print(f"VIN: {info.vin}")
    print(f"Марка: {info.make or 'не определена (код изготовителя не из списка VAG)'}")
    print(f"Год (10-й знак): {info.year or 'не определён'}")
    print(info.note)
    return 0


def cmd_ops(args) -> int:
    for o in OPERATIONS:
        print(f"{o.id:14} {o.title_ru}")
    return 0


def cmd_recon(args) -> int:
    adapters = all_adapters()
    client = _client(args, adapters)
    url = args.url or BASE_URL
    print(f"User-Agent: {client.ua}")
    print(f"robots.txt разрешает {url}: {client.is_allowed(url)}")
    try:
        page = client.get(url)
    except HttpError as exc:
        print(f"Не удалось загрузить: {exc}")
        return 1
    name = (urlparse(url).path.strip("/") or "home").replace("/", "_")
    out = config.data_dir(args.data_dir) / "recon"
    out.mkdir(exist_ok=True)
    target = out / (name if name.endswith(".html") else name + ".html")
    target.write_bytes(page.content)
    nav, docs = parse_listing(page.text(), url)
    print(f"Страница сохранена: {target} ({len(page.content) / 1024:.0f} КБ, из кэша: {page.from_cache})")
    print(f"Ссылок на страницы моделей/двигателей: {len(nav)}")
    print(f"Разделов руководств: {len(docs)}")
    for d in docs[:12]:
        codes = ",".join(d.engine_codes[:4])
        print(f"  [{d.kind}] {d.title[:70]}  #{d.anchor[:40]}  {('двигатели: ' + codes) if codes else ''}")
    print("\nЕсли разбор нашёл мало разделов, пришлите файл из папки recon: по нему подгоняется парсер.")
    return 0


def cmd_index(args) -> int:
    adapters = all_adapters()
    client, store = _client(args, adapters), _store(args)
    for adapter in adapters:
        try:
            count = adapter.refresh_index(client, store, args.model, args.engines, args.all_models,
                                          progress=print)
        except HttpError as exc:
            print(f"[{adapter.name}] ошибка: {exc}")
            return 1
        docs, nav = store.counts(adapter.name)
        print(f"[{adapter.name}] найдено в этом запуске: {count}; всего в индексе: "
              f"{docs} разделов, {nav} страниц. Запросов к сайту: {client.requests_made}")
    return 0


def _vehicle(args) -> Vehicle:
    vehicle = Vehicle(model=args.model, year=args.year,
                      engine_code=args.engine.upper() if args.engine else None)
    if args.vin:
        info = decode(args.vin)
        if info.valid_format:
            vehicle.vin, vehicle.make = info.vin, info.make
            vehicle.year = vehicle.year or info.year
        else:
            print(info.note)
    return vehicle


def cmd_docs(args) -> int:
    op = _operation(args.op)
    if not op:
        return 1
    adapters = all_adapters()
    store = _store(args)
    vehicle = _vehicle(args)
    for adapter in adapters:
        docs = adapter.find_documents(store, vehicle, op) if adapter.supports(vehicle) else []
        print(f"[{adapter.name}] подходящих разделов: {len(docs)}")
        for d in docs[:15]:
            print(f"  [{d.kind}] {d.title}\n      {d.url}   двигатели: {','.join(d.engine_codes) or '-'}")
    return 0


def cmd_ask(args) -> int:
    op = _operation(args.op)
    if not op:
        return 1
    adapters = all_adapters()
    client, store = _client(args, adapters), _store(args)
    vehicle = _vehicle(args)

    def confirm(doc, resources) -> bool:
        print(f"\nРаздел: {doc.title}")
        for r in resources:
            print(f"  будет загружено: {r.url} ({r.kind})")
        if args.yes:
            return True
        return input("Загрузить? [y/N] ").strip().lower() in ("y", "yes", "д", "да")

    result = run_query(adapters, store, client, vehicle, op, max_docs=args.max_docs,
                       max_resources=args.max_resources, confirm=confirm,
                       progress=lambda m: print("  " + m))
    print_findings(op, vehicle, result.findings)
    for note in result.notes:
        print("Примечание:", note)
    print(f"\nЗапросов к сайтам: {client.requests_made}")
    return 0


def cmd_analyze_file(args) -> int:
    op = _operation(args.op)
    if not op:
        return 1
    parts = read_file(args.path)
    if not parts:
        print("В файле не найден текст (возможно, это скан).")
        return 1
    findings = analyze(parts, op)
    print_findings(op, Vehicle(), findings)
    return 0


def cmd_gui(args) -> int:
    import threading

    from .app.launcher import open_ui
    from .app.server import AppServer, find_running, focus_running
    from .app.service import AppService
    from .app.window import run_native

    # Повторный запуск: программа уже работает, показываем её окно вместо второй копии.
    if find_running(args.port):
        url = f"http://127.0.0.1:{args.port}/"
        print(f"VinPartsHelper уже запущен: {url}")
        if not args.no_open and not focus_running(args.port):
            open_ui(url, app_window=not args.browser)      # у работающей копии нет своего окна
        return 0

    service = AppService(args.data_dir, delay=args.delay, use_cache=not args.no_cache)
    server = AppServer(service, args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"VinPartsHelper запущен: {server.url}")

    try:
        if args.no_open:
            if args.auto_exit:
                server.start_watchdog(args.idle_seconds)
            server.stop_event.wait()
        else:
            if not args.browser:
                if run_native(server, service.data_dir / "webview"):
                    return 0                                  # окно закрыли: выходим
                print(f"Окно приложения недоступно ({server.window_error}). Открываю в браузере.")
            if args.auto_exit:
                server.start_watchdog(args.idle_seconds)
                print("Программа завершится сама, когда вы закроете окно.")
            else:
                print("Чтобы выйти, нажмите «Выход» в окне программы или закройте это окно (Ctrl+C).")
            how = open_ui(server.url, app_window=not args.browser)
            if how == "browser":
                print("Открыто в браузере по умолчанию.")
            server.stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vinparts", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", help="папка для индекса и кэша (по умолчанию пользовательская)")
    p.add_argument("--delay", type=float, default=config.DEFAULT_DELAY_SECONDS,
                   help="пауза между запросами к сайту, сек (не меньше 2)")
    p.add_argument("--no-cache", action="store_true", help="не хранить скачанное на диске")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("vin", help="разобрать VIN (марка, год)")
    s.add_argument("vin")
    s.set_defaults(func=cmd_vin)

    s = sub.add_parser("ops", help="список известных операций")
    s.set_defaults(func=cmd_ops)

    s = sub.add_parser("recon", help="разведка: проверить robots.txt и разобрать страницу")
    s.add_argument("--url", help="страница vwts.ru (по умолчанию главная)")
    s.set_defaults(func=cmd_recon)

    s = sub.add_parser("index", help="обновить локальный индекс ссылок")
    s.add_argument("--model", action="append", help="модель, страницу которой загрузить (можно несколько раз)")
    s.add_argument("--engines", action="store_true", help="загрузить страницы руководств по двигателям")
    s.add_argument("--all-models", action="store_true",
                   help="загрузить страницы ВСЕХ моделей (около сотни запросов с паузой; долго, но один раз)")
    s.set_defaults(func=cmd_index)

    for name, func, helptext in (("docs", cmd_docs, "показать подходящие разделы без загрузки текста"),
                                 ("ask", cmd_ask, "найти пометки о замене деталей для операции")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--op", required=True, help='операция, например "цепь грм"')
        s.add_argument("--model", help='модель, например "golf 7"')
        s.add_argument("--engine", help="код двигателя, например CJSA")
        s.add_argument("--year", type=int)
        s.add_argument("--vin")
        if name == "ask":
            s.add_argument("--max-docs", type=int, default=2)
            s.add_argument("--max-resources", type=int, default=3)
            s.add_argument("--yes", action="store_true", help="не спрашивать подтверждение загрузки")
        s.set_defaults(func=func)

    s = sub.add_parser("gui", help="запустить оконное приложение (рекомендуется)")
    s.add_argument("--port", type=int, default=8765, help="порт на 127.0.0.1 (если занят, берётся свободный)")
    s.add_argument("--no-open", action="store_true", help="не открывать окно автоматически")
    s.add_argument("--browser", action="store_true", help="не использовать окно приложения, открыть во вкладке браузера")
    s.add_argument("--auto-exit", action="store_true", help="завершиться, когда окно закрыто")
    s.add_argument("--idle-seconds", type=float, default=90.0, help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_gui)

    s = sub.add_parser("analyze-file", help="разобрать локальный PDF/HTML/текстовый файл")
    s.add_argument("path", type=Path)
    s.add_argument("--op", required=True)
    s.set_defaults(func=cmd_analyze_file)
    return p


def main(argv: list[str] | None = None) -> int:
    _setup_output()
    args = build_parser().parse_args(argv)
    if args.delay < 2:
        print("Пауза меньше 2 секунд не допускается (вежливость к сайту).")
        return 2
    try:
        return args.func(args)
    except HttpError as exc:
        print(f"Ошибка: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
