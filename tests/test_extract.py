from datetime import date

from tests.conftest import fixture_text, make_pdf
from vinparts.extract import analyze, extract_from_sentence, sentences
from vinparts.glossary import gloss
from vinparts.models import TextPart
from vinparts.operations import match_operation
from vinparts.readers import read_pdf_bytes
from vinparts.vin import decode


def by_part(findings):
    return {f.part.lower(): f for f in findings}


def test_operation_matching_handles_case_endings_and_english():
    for text in ("цепь грм", "Замена цепи ГРМ", "замена цепочки газораспределительного", "timing chain"):
        assert match_operation(text).id == "timing_chain", text
    assert match_operation("ремень грм").id == "timing_belt"
    assert match_operation("замена ремня ГРМ").id == "timing_belt"
    assert match_operation("колодки").id == "brake_pads"
    assert match_operation("что-то непонятное") is None


def test_sentence_patterns():
    assert extract_from_sentence("Always replace chain tensioner after removing.") == [
        ("chain tensioner", "required")]
    assert ("Self-locking bolts", "required") in extract_from_sentence("Self-locking bolts must always be replaced.")
    assert ("Gasket", "required") in extract_from_sentence("Gasket - replace after removing")
    assert ("timing chain", "conditional") in extract_from_sentence("Replace timing chain if damaged or worn.")
    assert ("sealing ring", "required") in extract_from_sentence("Do not reuse sealing ring.")
    assert ("guide rails", "check") in extract_from_sentence("Check the guide rails for wear.")
    names = [n for n, _ in extract_from_sentence("Replace the engine oil and the oil filter after the repair.")]
    assert names == ["engine oil", "oil filter"]
    # следующее действие после «and» деталью не считается
    assert [n for n, _ in extract_from_sentence("Replace chain tensioner and check the guide rails.")] == [
        "chain tensioner"]
    assert extract_from_sentence("Replace.") == []
    # «Replace if damaged» без объекта не должно давать «деталь» if damaged
    assert extract_from_sentence("Replace if damaged or worn.") == []
    assert extract_from_sentence("Mark the running direction before removing.") == []


def test_analyze_synthetic_chain_manual():
    parts = [TextPart(fixture_text("chain_manual.txt"), 12, "https://example/manual.pdf", "Engine manual")]
    findings = by_part(analyze(parts, match_operation("цепь грм")))
    assert findings["chain tensioner"].role == "required"
    assert findings["chain tensioner"].part_ru == "натяжитель цепи"
    assert findings["chain tensioner"].page == 12
    assert findings["self-locking bolts"].role == "required"
    assert findings["timing chain"].role == "conditional"
    assert findings["gasket"].role == "required"
    assert findings["sprockets"].role == "recommended"
    assert findings["chain guide"].role == "conditional"   # «must … when …» — это условие, а не «всегда»
    assert findings["guide rails"].role == "check"
    assert findings["sealing ring"].role == "required"
    assert "engine oil" in findings
    # самое важное первым
    roles = [f.role for f in analyze(parts, match_operation("цепь грм"))]
    assert roles == sorted(roles, key=["required", "recommended", "conditional", "check"].index)


def test_irrelevant_text_gives_nothing():
    parts = [TextPart("Replace the cabin filter every 30000 km. Windscreen washer fluid.", 1, "u", "t")]
    assert analyze(parts, match_operation("цепь грм")) == []


def test_pdf_roundtrip_and_pages():
    pdf = make_pdf(["Cover page", "Timing chain\nAlways replace chain tensioner after removing."])
    parts = read_pdf_bytes(pdf, "u", "t")
    assert [p.page for p in parts] == [1, 2]
    findings = analyze(parts, match_operation("цепь грм"))
    assert findings and findings[0].part == "chain tensioner" and findings[0].page == 2


def test_gloss():
    assert gloss("chain tensioner") == "натяжитель цепи"
    assert gloss("sprockets") == "звёздочка"
    assert gloss("Self-locking bolts") == "самоконтрящиеся болты"
    assert gloss("nothing known here") is None


def test_vin_decode():
    info = decode("WVWZZZAUZFW123456", today=date(2026, 11, 16))
    assert info.valid_format and info.make == "Volkswagen" and info.year == 2015
    assert decode("TMBZZZ5E1KB123456", today=date(2026, 11, 16)).make == "Škoda"
    assert not decode("TOO-SHORT").valid_format
    assert not decode("WVWZZZAUZFW12345O").valid_format  # буква O запрещена


def test_assembly_overview_checklist_format():
    """Формат сборочного обзора VAG: «N - Деталь» и пометки со значком ❑ на отдельных строках."""
    parts = [TextPart(fixture_text("assembly_overview.txt"), 140, "https://example.org/m.pdf", "Engine manual")]
    findings = {f.part: f for f in analyze(parts, match_operation("ремень грм"))}
    assert findings["Bolt (180 Nm +135°)"].role == "required"
    assert findings["Nut (20 Nm +45°)"].role == "required"
    assert "Nut (20 Nm)" not in findings                     # гайка без пометки о замене не попадает в список
    assert findings["Stud (15 Nm)"].role == "conditional"
    assert findings["Toothed belt"].role == "check" and findings["Toothed belt"].part_ru == "ремень ГРМ"
    assert findings["Seal"].role == "required"               # перенос слова «re‐\nmoval» склеен
    assert "Renew after removal" in findings["Bolt (180 Nm +135°)"].quote
