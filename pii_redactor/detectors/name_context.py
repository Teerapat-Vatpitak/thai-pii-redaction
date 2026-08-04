"""Context-based Thai name detection (recall booster for the CRF NER).

The thainer CRF NER misses some names and clips others (e.g. a leading title
"นาย" shifts the span so the surname leaks). Thai names are reliably introduced
by a small set of high-precision cues — titles (นาย/นาง/นางสาว/…) and explicit
name labels (ผมชื่อ…, ลงชื่อ). This pass works on word TOKENS (not raw regex)
so it does not fire on substrings like "นายก" or "คุณภาพ", and captures the
following 1–2 name tokens.

Emitted entities are TB/NAME with a slightly higher score than the CRF, so when
they overlap a partial CRF hit the longer, complete name wins de-duplication.
Recall > precision: a few extra cues are preferred over missed names.
"""

from __future__ import annotations

import re
import uuid
from difflib import SequenceMatcher

from pythainlp.tokenize import word_tokenize

# The document/form-compound list `_name_hygiene` rejects a CRF NAME span on.
# Imported, not copied, so the two rules cannot drift apart -- a form header
# this module admitted as a glued name would be rejected one layer later
# anyway. Safe at module scope: tb_detector imports name_context only inside
# function bodies, so this direction closes no cycle (verified both ways).
from pii_redactor.detectors.tb_detector import _NAME_DOC_COMPOUND_RE
from pii_redactor.models import Entity

# Titles that, as standalone tokens, almost always precede a person name.
_TITLES = {
    "นาย",
    "นาง",
    "นางสาว",
    "น.ส.",
    "ด.ช.",
    "ด.ญ.",
    "เด็กชาย",
    "เด็กหญิง",
}
# "ชื่อ" is only a name cue right after a first-person pronoun.
_PRONOUNS = {"ผม", "ดิฉัน", "ฉัน", "หนู", "กระผม", "ข้าพเจ้า"}
# Cues that introduce a name with no "ชื่อ" in between. Thai official letters
# open with "ข้าพเจ้า <name>", so the name arrives directly after the cue --
# the pronoun+ชื่อ rule above never fires on them, which is how
# "ข้าพเจ้า วิชัย ประสงค์ดี" went out intact.
#
# ONLY tokens newmm actually keeps whole belong here. ผู้ร้อง / ผู้ร้องเรียน /
# ผู้ยื่นคำร้อง were in this set and were dead code: newmm splits them into
# ['ผู้', 'ร้อง'] etc., and the loop below compares whole tokens, so they never
# matched once. Verified with word_tokenize before trimming the set. Adding a
# cue here without checking that is how a fix ships doing nothing.
_DIRECT_NAME_CUES = {"ข้าพเจ้า", "ผู้เสียหาย"}
# Compound self-introductions newmm may keep as one token.
_INTRO_COMPOUND = {"ผมชื่อ", "ดิฉันชื่อ", "ฉันชื่อ", "หนูชื่อ", "ลงชื่อ"}

# {1,} not {2,}: newmm splits some real first names into single-char tokens
# (สราวุธ -> ส|รา|วุธ), and the per-entity >=2-char chokepoint still applies.
_THAI_WORD = re.compile(r"^[ก-๛]+$")
_NEVER_NAME_CHARS = {"ๆ", "ฯ"}
# Thai-script tokens that are not names even right after a cue.
_NOT_NAME = {
    "ชื่อ",
    "นามสกุล",
    "คือ",
    "ครับ",
    "ค่ะ",
    "คะ",
    "นะ",
    "และ",
    "ที่",
    "ของ",
    "จาก",
    "อยู่",
    "เป็น",
    "อายุ",
    "มา",
    "ไป",
    "ได้",
    "เบอร์",
    "อีเมล",
    "โทร",
    # document-label nouns ("ผมชื่อ สมชาย รหัสพนักงาน …") — never part of a
    # person name; without these the group collector swallows the label after
    # the name as a fake surname. Both compound tokens and their newmm splits.
    "เลข",
    "หมายเลข",
    "บัตร",
    "บัตรประชาชน",
    "เลขบัตรประชาชน",
    "ประชาชน",
    "รหัส",
    "รหัสพนักงาน",
    "พนักงาน",
    "บัญชี",
    "เลขบัญชี",
    "เลขที่บัญชี",
    "ธนาคาร",
    "โทรศัพท์",
    "มือถือ",
    "ที่อยู่",
    "ทะเบียน",
    "เอกสาร",
}


_NOT_NAME |= {"เลขที่", "หนังสือเดินทาง", "ลายมือชื่อ", "รายการ", "เงื่อนไข"}

# Form-label nouns and the standard letter closing that `_name_hygiene`'s
# tail-segment gate leaked as NAME entities (measured: 12 gold false positives
# and the HR-letter/A-B repros in the branch's final review). Each entry is the
# LEADING newmm token of a measured false-positive segment --
# "เลขประจำตัว"(ประชาชน) x4, "ตำแหน่ง", "อาชีพ" -- except the last, which newmm
# keeps whole: "ขอแสดงความนับถือ" is the exact string the direct-cue space veto
# further down was written to stop, and segmentation let it back in through a
# different door. Compounds/whole tokens only, never prefixes.
_NOT_NAME |= {"เลขประจำตัว", "ตำแหน่ง", "อาชีพ", "ขอแสดงความนับถือ"}

# The formal-letter salutation verb ("เรียน ผู้ปกครองของนักเรียน" — 'to
# inform'), never a Thai given name. A role cue firing inside a document
# title vouched for it and minted "เรียน ผู้ปกครอง" as a person (measured
# gold false positive, gf16); blocking it as a name TOKEN fixes every
# collector at once without touching CRF or title spans.
_NOT_NAME |= {"เรียน"}

# Trailing field labels the CRF glues onto a NAME span on label-dense form
# lines (boundary inventory B2, 20 measured rows): วันเกิด and ความสัมพันธ์
# are labels newmm keeps whole, so the existing วัน/ความ entries never see
# them; ประจำตัว is the split-off second token of รหัสประจำตัว (the compound
# เลขประจำตัว is already listed, the bare token was not). Labels, never
# names — same closed-list idiom as the entries above.
_NOT_NAME |= {"วันเกิด", "ความสัมพันธ์", "ประจำตัว"}

# Verbs/functional tokens that begin prose, never a Thai given name. Exact
# whole-token matches only — a prefix rule would kill real names (การุณ).
_LEAD_STOP = {
    "ต้อง",
    "ควร",
    "จะ",
    "ให้",
    "โปรด",
    "กรุณา",
    "สามารถ",
    "ขอ",
    "กรอก",
    "แนบ",
    "แสดง",
    "ชำระ",
    "ดำเนิน",
    "ดำเนินการ",
    "ยอมรับ",
    "ได้",
    "ได้รับ",
    "รับ",
    "อยู่",
    "เป็น",
    "คือ",
    "ประสงค์",
    "ทุก",
    "ราย",
    # Second-person honorific opening a sentence to the reader
    # ("ท่านมียอดค้างชำระ" -- a measured gold NAME false positive through
    # `_name_hygiene` segmentation). Never a Thai given name.
    "ท่าน",
}
_ACCOUNT_TYPES = {"ออมทรัพย์", "กระแสรายวัน", "ฝากประจำ"}

# Role cues, matched at CHARACTER level over the raw text — newmm splits
# ผู้-compounds (ผู้ป่วย -> ผู้|ป่วย), so token-level matching silently never
# fires (the documented dead-code trap). Each cue carries the prose
# continuations that must veto it when GLUED directly to the cue: the veto
# list is what separates "ผู้ป่วย สมบูรณ์ ทรงศิริ" (a labeled person) from
# "ผู้ป่วยใน ห้องพิเศษ" (a ward category). Longest cue first so
# ผู้ยื่นอุทธรณ์ is not consumed as ผู้ยื่น + อุทธรณ์-as-name.
_ROLE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ผู้ค้ำประกันเงินกู้", ("ต้อง", "ควร", "มี", "ร่วม")),
    ("ผู้รับมอบอำนาจ", ("ต้อง", "ควร", "ช่วง")),
    ("ผู้รับการตรวจ", ("ต้อง", "ควร")),
    ("ผู้ยื่นอุทธรณ์", ("ต้อง", "ควร")),
    ("ผู้ยื่นคำร้อง", ("ต้อง", "ควร")),
    ("ผู้ค้ำประกัน", ("ต้อง", "ควร", "มี", "ร่วม")),
    ("ผู้เอาประกันภัย", ("ต้อง", "ควร")),
    ("ผู้เสียหาย", ("ต้อง", "ควร", "ได้", "แจ้ง", "ถูก", "มี", "ให้", "ไม่", "จะ", "ทั้ง")),
    ("ผู้ปกครอง", ("ต้อง", "ควร", "ของ", "นักเรียน", "และ")),
    ("ผู้สั่งซื้อ", ("สินค้า", "ต้อง", "ควร")),
    ("ผู้ถือบัตร", ("ต้อง", "ควร", "สามารถ", "ทุก")),
    ("ผู้เดินทาง", ("ต้อง", "ควร", "ทุก", "ที่")),
    ("ผู้ขับขี่", ("ต้อง", "ควร", "ที่", "ทุก")),
    # The fixed emergency-contact form phrase (lf11). Its own entry, tried
    # before the bare ผู้ติดต่อ, because the กรณี veto below would otherwise
    # silence the row entirely: the CRF carries no PERSON span there, so the
    # compound cue is the only thing that keeps the contact's name masked.
    ("ผู้ติดต่อกรณีฉุกเฉิน", ("ต้อง", "ควร", "ติดต่อ", "โทร", "ได้", "แจ้ง")),
    # กรณี: "ผู้ติดต่อกรณีฉุกเฉิน กาญจนา ..." — without the veto the collector
    # takes "กรณีฉุกเฉิน กาญจนา" as the two name groups (B6) and that wrong
    # span evicts the real name in dedupe.
    ("ผู้ติดต่อ", ("หลัก", "สำรอง", "สอบถาม", "กลับ", "ได้", "ประสาน", "กรณี")),
    ("ผู้สมัคร", ("งาน", "สอบ", "ทุก", "ที่", "สามารถ", "รหัส")),
    ("ผู้แจ้ง", ("ความ", "เบาะแส", "เตือน")),
    ("ผู้ยื่น", ("ภาษี", "แบบ")),
    # หญิง/ชาย are NOT vetoes: they are skipped as qualifiers (see
    # _ROLE_QUALIFIERS below). Vetoing them killed the cue outright, and where
    # the CRF carries no PERSON span ("ผู้ป่วยชาย ธงชัย รักถิ่น") the whole
    # name then shipped in the clear — a recall regression against base found
    # by the 2026-08-04 review.
    ("ผู้ป่วย", ("ใน", "นอก", "ราย", "ทุก", "ต้อง", "ควร", "ที่", "จะ", "ได้", "เรื้อรัง")),
    ("ผู้กู้", ("ร่วม", "ยืม", "ต้อง", "ควร")),
    ("มอบอำนาจให้", ("__require_space__",)),
    # Card/receipt issuance rows ("4024-... ออกให้ ปกรณ์เกียรติ ธนวัฒนา").
    # __require_space__ makes the glued forms (ออกให้แก่, ออกให้ทะเบียน)
    # no-ops — a stated recall cost on the แก่ form.
    ("ออกให้", ("__require_space__",)),
    ("ชื่อบัญชี", ("ผู้ใช้",)),
)
# Tokens that may sit between a role cue and the name ("ผู้ป่วยชื่อวิภาวดี",
# "ผู้ค้ำประกันเงินกู้คือ สราวุธ").
_ROLE_LINKERS = {"คือ", "ชื่อ", "ได้แก่"}
# Gender qualifiers the ward/police register glues onto the role word
# ("ผู้ป่วยหญิง รัตนา แสงวิเชียร", md03/lf17). They are grammatical
# qualifiers, never the person's first name, so the collector must step OVER
# them — the same idiom as _ROLE_LINKERS. Treating them as vetoes instead
# silenced the cue entirely and unmasked the name wherever the CRF had no
# PERSON span of its own. Because a skipped qualifier is left unmasked, the
# skip additionally demands two REAL groups after it (see `_role_cue_names`):
# a single-group fallback here would mint the following prose word
# ("ผู้ป่วยหญิง อายุ 52 ปี") as a person.
_ROLE_QUALIFIERS = {"หญิง", "ชาย"}

# Bare "ชื่อ" as a field label: only at line start, only with a delimiter, so
# it cannot fire inside ชื่อบัญชี/ชื่อบริษัท or mid-sentence prose.
#
# The delimiter also admits a LINE BREAK. OCR of a government form puts the
# field label on its own physical line and its value on the next one
# ("…\nชื่อ\nพิมพ์ใจ แสนดี\n…", reproduced from ภ.ง.ด.91), so a horizontal-only
# delimiter class made the label vouch for nothing. The delimiter itself stays
# mandatory -- that is what keeps ชื่อบัญชี / ชื่อบริษัท / ชื่อไฟล์ out, since a
# Thai letter is neither a space nor a newline.
_LINE_NAME_LABEL_RE = re.compile(r"(?m)^[ \t]*ชื่อ(?:-นามสกุล)?(?:[ \t:：]+|[ \t:：]*\r?\n)")
# OCR can join nearby form fields on one line, so the label is allowed away
# from the line start here — but it still has to be the WORD ชื่อ. Without the
# lookbehind, any prose carrying one of these field words ahead of a compound
# ending in ชื่อ ("ดูรายชื่อ สาขา ทั่วประเทศ") tags the next two words as a
# person, which is the same trap the line-anchored pattern above avoids.
_INLINE_NAME_LABEL_RE = re.compile(
    r"(?m)(?:สัญชาติ|คำนำหน้า|เพศ)[^\r\n]{0,30}?(?<![ก-๛])ชื่อ(?:-นามสกุล)?[ \t:：]+"
)
_NON_PERSON_LEADS = {
    "บริษัท",
    "ห้าง",
    "ธนาคาร",
    "โรงพยาบาล",
    "มหาวิทยาลัย",
    "โรงเรียน",
    "สำนักงาน",
    "โรงงาน",
    "มูลนิธิ",
    "โครงการ",
    "สมาคม",
    "สหกรณ์",
    "หน่วยงาน",
}
# First-collected-token check for the role and roster passes: a cue that
# vouches for "who follows" must not vouch for a juristic person. หจก/บจก are
# the abbreviated forms (ห้างหุ้นส่วนจำกัด / บริษัทจำกัด) leading vendor rows
# in procurement rosters; the full words are already in _NON_PERSON_LEADS.
_ORG_LEAD_TOKENS = _NON_PERSON_LEADS | {"หจก", "บจก"}

# "<kinship>ชื่อ <first> <last>" — คุณแม่ชื่อ สมหญิง รักไทย. The kinship word
# is what makes bare ชื่อ a person label here; กรอกชื่อ/ระบุชื่อ stay form
# instructions and never fire.
_KINSHIP_NAME_LABEL_RE = re.compile(
    r"(?:คุณแม่|คุณพ่อ|แม่|พ่อ|พี่สาว|พี่ชาย|พี่|น้องสาว|น้องชาย|น้อง|ลูกสาว|ลูกชาย|ลูก"
    r"|ภรรยา|สามี|ป้า|ลุง|ย่า|ยาย|ปู่|ตา|หลาน|เพื่อน|แฟน)ชื่อ[ \t:：]*"
)

# Numbered rosters need header evidence — numbered lists are also agendas and
# invoices, and "1. การชำระ เงินล่วงหน้า" is two Thai tokens shaped like a
# name. The header is what says these lines enumerate PEOPLE. ผลการคัดเลือก
# (selection results) and ผู้มาประชุม/ผู้เข้าร่วมประชุม (the attendee headers
# of the official Thai minutes template) are register vocabulary; they are
# only safe alongside the _ORG_LEAD_TOKENS check in `_roster_names`, because
# a selection result can enumerate juristic persons.
_ROSTER_HEADER_RE = re.compile(
    r"รายชื่อ|ผู้เข้าสอบ|ผู้เข้าพัก|ผู้มีสิทธิ์|ผู้ผ่านการ|ทะเบียนผู้"
    r"|ผลการคัดเลือก|ผู้มาประชุม|ผู้เข้าร่วมประชุม"
)
_ROSTER_CUE_RE = re.compile(r"(?m)(?:^|(?<=\s))(?:ลำดับที่[ \t]*\d+[ \t.]*|\d{1,3}\.[ \t]+)")
_ROSTER_HEADER_WINDOW = 300

# A two-group Thai name immediately followed by a passport-format value or
# the word passport (hotel/visa/tour rosters).
_NAME_BEFORE_PASSPORT_RE = re.compile(
    r"([ก-๛]{2,25})[ \t]([ก-๛]{2,25})[ \t]+(?=passport|[A-Z]{2}\d{7})"
)

# Latin-script names: the Thai CRF never tags them. Cue-driven extraction
# only (a global capitalized-bigram scan plus proximity is how "Name Bangkok
# Bank" becomes a person), with an org/place component stoplist.
_LATIN_CUE_RE = re.compile(
    r"(?:(?:Name|ชื่อ)[ \t]*[:：=][ \t]*|(?:Name|ชื่อ)[ \t]+|contact person[ \t:：]*"
    r"|Mr\.?[ \t]+|Ms\.?[ \t]+|Mrs\.?[ \t]+|ผู้ยื่น[ \t]+|ผู้แจ้ง[ \t]+"
    r"|ที่นั่งสอบ[ \t]*[A-Za-z]?\d+[ \t]+)"
)
_LATIN_NAME_RE = re.compile(r"[A-Z][a-z]{1,20}(?:[ \t](?:[A-Z]\.|[A-Z][a-z]{1,20})){1,3}")
_LATIN_TRAILING_PASSPORT_RE = re.compile(
    r"([A-Z][a-z]{1,20}(?:[ \t](?:[A-Z]\.|[A-Z][a-z]{1,20})){1,2})[ \t]+(?=passport|[A-Z]{2}\d{7})"
)
_LATIN_ORG_STOP = {
    "bank",
    "company",
    "limited",
    "public",
    "hospital",
    "university",
    "hotel",
    "road",
    "river",
    "province",
    "district",
    "tower",
    "office",
    "department",
    "faculty",
    "school",
    "service",
    "customer",
    "group",
    "branch",
    "building",
    "resort",
    "airport",
    "station",
    "palace",
    "temple",
    "market",
    "mall",
    "co",
    "ltd",
    "plc",
}


def _is_name_token(tok: str) -> bool:
    return (
        bool(_THAI_WORD.match(tok))
        and tok not in _NOT_NAME
        and tok not in _TITLES
        and tok not in _NEVER_NAME_CHARS
    )


# --- glued (space-deleted) Thai name runs -----------------------------------
# OCR deletes the space inside a Thai name ("สมชาย ใจดี" -> "สมชายใจดี"), and
# every name shape in this module and in the isolated-line retry required a
# space or two token groups, so a glued name qualified for nothing.
#
# The discriminator is the TOKENIZER, not the shape: Thai given names and
# surnames are not dictionary words, so newmm always splits a real glued name
# into two or more pieces ("สมชายใจดี" -> สม|ชาย|ใจดี, "มาลีรักดี" -> มาลี|รัก|ดี),
# while the prose and form nouns that sit in exactly these positions are single
# dictionary tokens ("ขอแสดงความนับถือ" -- the standard closing of a Thai
# official letter and the verified false positive the space veto was added for
# -- plus ความเห็น, นายทะเบียน, จดทะเบียนสมรส, สำนักงานเขต, หมายเหตุ). The
# stop set below covers the multi-token form/document compounds the token
# count alone lets through.
_GLUED_NAME_MIN_CHARS = 4
_GLUED_NAME_MAX_CHARS = 25
_GLUED_NAME_MAX_TOKENS = 4
_GLUED_RUN_RE = re.compile(r"[ก-ฮเ-ไ][ก-ฮะ-์]*")
_NON_PERSON_LEAD_PREFIXES = tuple(sorted(_NON_PERSON_LEADS))
# Form/document nouns and grammatical particles that are never part of a person
# name. Checked per TOKEN (not as a prefix) so a real name sharing a prefix is
# unaffected. Each entry was observed leaking a gov-form header or a prose
# fragment through the token-count rule above -- and each is only here because
# it leaked: `ใบ` and `แบบ` would have covered nothing measured and would have
# rejected the real given names `ใบเฟิร์น` / `แบบบุญมี` that tb_detector's own
# compound rule is documented to preserve (recall > precision).
_GLUED_RUN_STOP = {
    "การ",
    "ความ",
    "ผู้",
    "ร้องขอ",
    "วัน",
    "เดือน",
    "ปี",
    "ปีเกิด",
    "ที่อยู่",
    "ข้อมูล",
    "รายละเอียด",
    "ส่วนบุคคล",
    "บุคคล",
    "เงินได้",
    "ภาษี",
    "ภาษีเงินได้",
    "จดทะเบียน",
    "ทะเบียน",
    "สาขา",
    "ฝ่าย",
    "แผนก",
    "หนังสือ",
    "คำร้อง",
    "สำเนา",
    "ยินยอม",
    "ยอมให้",
    "รับรอง",
    "เพิ่มเติม",
    "ชำระเงิน",
    "ค่าธรรมเนียม",
    "หมายเหตุ",
}


def is_glued_name_run(run: str) -> bool:
    """True when a spaceless Thai run may be a name whose space OCR deleted."""
    if not (_GLUED_NAME_MIN_CHARS <= len(run) <= _GLUED_NAME_MAX_CHARS):
        return False
    if _GLUED_RUN_RE.fullmatch(run) is None:
        return False
    if run in _NOT_NAME or run in _TITLES:
        return False
    if run.startswith(_NON_PERSON_LEAD_PREFIXES):
        return False
    if _NAME_DOC_COMPOUND_RE.match(run):
        return False
    tokens = [t for t in word_tokenize(run, keep_whitespace=False) if t.strip()]
    if not (2 <= len(tokens) <= _GLUED_NAME_MAX_TOKENS):
        return False
    return all(
        _is_name_token(t) and t not in _LEAD_STOP and t not in _GLUED_RUN_STOP for t in tokens
    )


def is_non_person_segment(seg: str) -> bool:
    """True when a space-separated Thai run is a form label or prose fragment.

    Shared with `tb_detector._name_hygiene`'s tail-segment gate, so the two
    rules that reject a non-person Thai run agree instead of each carrying its
    own list. The decision is the LEADING newmm token only -- the same idiom
    `_collect_two_groups` uses ("a leading _LEAD_STOP token aborts it") and for
    the same reason: checking EVERY token would reject real surnames the
    tokenizer splits onto a stop word ("ทองอยู่" -> ทอง|อยู่, "ชลธิชา ทองอยู่"
    is a person). Every measured form-label false positive leads with its label
    noun, so the leading token is where the evidence actually is.
    """
    tokens = [t for t in word_tokenize(seg, keep_whitespace=False) if t.strip()]
    if not tokens:
        return True
    lead = tokens[0]
    return (
        lead in _NOT_NAME
        or lead in _LEAD_STOP
        or lead in _GLUED_RUN_STOP
        or lead in _NON_PERSON_LEADS
    )


# --- same-line role/label trimming for CRF NAME spans (B1/B2/B3) ------------
# On label-dense form lines the CRF glues a leading role word
# ("ผู้จัดการฝ่ายขาย วิชัย ประสงค์ดี") or a trailing field label
# ("อรุณี วัฒนสิทธิ์ เลขประจำตัวประชาชน") onto the person's name in ONE span.
# Gold convention (docs/annotation-guidelines.md): role words and field labels
# are context, not value. Trimming UNMASKS the trimmed text, so the rules are
# deliberately strict:
#
# - Whole-token, closed-lexicon evidence only. A token is trimmed because it
#   IS a lexicon entry, never because a prefix of it matches one; a trailing
#   group is truncated only when EVERY token in it is a label token, so a
#   surname newmm splits onto a label/stop word (ทองอยู่ -> ทอง|อยู่,
#   บัตรงาม -> บัตร|งาม) survives on its non-matching half.
# - The ผู้ carve-out ("ผู้-role compounds included"): no Thai given name
#   begins with the nominalizer ผู้, so a leading token ผู้X is a role
#   compound. When newmm splits the compound instead (ผู้|รับเงิน), the bare
#   ผู้ token vouches for the rest of ITS group — the same lead-token idiom
#   as `is_non_person_segment`, and the same shape
#   `tb_detector._ISOLATED_NAME_PREFIX_RE` already strips. A ผู้-compound
#   lead with MORE tokens glued after it (OCR: "ผู้ป่วยรัตนา") trims the
#   compound token only, so a glued first name is never eaten.
# - >= 2 horizontal-space-separated groups (first + last name) must remain
#   after every step. When in doubt the span is kept unchanged — over-masking
#   a role word is the safe direction, unmasking is not.
_TRIM_GROUP_RE = re.compile(r"[^ \t]+")
_ROLE_NOMINALIZER = "ผู้"


def _head_trim_lexicon() -> frozenset[str]:
    # Built per call (the sets above receive |= additions across the module,
    # and a module-level snapshot taken mid-file would silently miss them).
    #
    # _LEAD_STOP is deliberately NOT here. It documents itself as words that
    # never START a name in prose — which is a reason to refuse to BEGIN
    # collecting a name at one (what `_collect_two_groups` and
    # `is_non_person_segment` use it for), not evidence that the word is not a
    # name. ประสงค์ is an attested Thai given name, and using the list here
    # UNMASKED it out of a CRF span that had it right ("... คือ ประสงค์ ดีงาม
    # สมศรี ใจดี", 2026-08-04 review). Role words and field labels stay.
    return frozenset(_NOT_NAME | _GLUED_RUN_STOP | _NON_PERSON_LEADS)


def trim_same_line_name_edges(seg: str) -> tuple[int, int]:
    """Trim role-word heads and truncate at trailing field labels.

    Returns (start, end) offsets into ``seg``; (0, len(seg)) shape when
    nothing qualifies. Used by `tb_detector._name_hygiene` on the no-newline
    span and the head segment — the 61 measured B1/B2/B3 rows are all
    same-line spans.
    """

    def groups(lo: int, hi: int) -> list[tuple[int, int]]:
        return [(lo + m.start(), lo + m.end()) for m in _TRIM_GROUP_RE.finditer(seg[lo:hi])]

    def group_tokens(lo: int, hi: int) -> list[str]:
        return [t for t in word_tokenize(seg[lo:hi], keep_whitespace=False) if t.strip()]

    start, end = 0, len(seg)
    # B2 tail first: a trailing label group must never count toward the head
    # trim's two-group floor — "ผู้ค้ำประกัน ดารณี อายุ" head-first would trim
    # the role and leave "ดารณี อายุ" (a floor met by a label group protects
    # nothing); tail-first removes the label and the floor then correctly
    # blocks the head trim.
    gs = groups(start, end)
    for i in range(2, len(gs)):
        toks = group_tokens(*gs[i])
        if toks and all(t in _NOT_NAME for t in toks):
            end = gs[i - 1][1]
            break
    # B1 head: trim leading role/label groups while >= 2 groups remain.
    head_lex = _head_trim_lexicon()
    while True:
        gs = groups(start, end)
        if not gs:
            break
        g_lo, g_hi = gs[0]
        toks = group_tokens(g_lo, g_hi)
        if not toks:
            break
        lead = toks[0]
        if all(t in head_lex for t in toks):
            new_start = g_hi
        elif lead == _ROLE_NOMINALIZER:
            # newmm split the compound. The bare ผู้ vouches for the ROLE word
            # it nominalizes and for nothing further: on a glued OCR row it
            # splits ผู้ค้ำสมศรี into ผู้|ค้ำ|สม|ศรี, and consuming the whole
            # space group took the given name with the role (2026-08-04
            # review). Advance past ผู้ + one role token only.
            new_start = min(g_lo + len(lead) + (len(toks[1]) if len(toks) > 1 else 0), g_hi)
        elif lead.startswith(_ROLE_NOMINALIZER):
            new_start = g_lo + len(lead)
        else:
            break
        if len(groups(new_start, end)) < 2:
            break
        start = new_start
    gs = groups(start, end)
    if gs:
        start, end = gs[0][0], gs[-1][1]
    return start, end


def _make_name(text: str, start: int, end: int, score: float) -> Entity:
    return Entity(
        entity_id=str(uuid.uuid4()),
        redact_type="TB",
        data_type="NAME",
        span=(start, end),
        score=score,
        original_text=text[start:end],
    )


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    tokens = word_tokenize(text, keep_whitespace=True)
    spans: list[tuple[str, int, int]] = []
    pos = 0
    for t in tokens:
        i = text.find(t, pos)
        if i == -1:
            i = pos
        spans.append((t, i, i + len(t)))
        pos = i + len(t)
    return spans


def _collect_two_groups(
    spans: list[tuple[str, int, int]], start_idx: int
) -> tuple[int, int] | None:
    """Collect exactly two horizontal-space-separated groups of name tokens.

    Two groups (first + last name) are REQUIRED — a single Thai token after a
    role word is far more often prose than a mononym. Whitespace containing a
    newline ends the attempt; a leading _LEAD_STOP token aborts it (verbs
    start sentences, not names).
    """
    n = len(spans)
    collected: list[tuple[int, int]] = []
    groups = 0
    first_token_of_name = True
    j = start_idx
    while j < n:
        tok, ts, te = spans[j]
        if tok.strip() == "":
            if any(ch in tok for ch in "\n\r"):
                break
            if not collected:
                j += 1
                continue
            if groups == 1:
                break
            groups = 1
            first_token_of_name = True  # next token starts the second group
            j += 1
            continue
        if not _is_name_token(tok) or te - ts > 25:
            break
        if first_token_of_name and tok in _LEAD_STOP:
            # a verb opening EITHER group means this is prose, not a name
            return None
        if first_token_of_name and groups == 0 and tok in _ACCOUNT_TYPES:
            return None
        first_token_of_name = False
        collected.append((ts, te))
        j += 1
    if not collected or groups < 1:
        return None
    return collected[0][0], collected[-1][1]


def _index_after(spans: list[tuple[str, int, int]], char_pos: int) -> int | None:
    """First token index starting at or after char_pos; None if a token
    straddles the boundary (cannot align a glued cue to token space)."""
    for idx, (_t, s, e) in enumerate(spans):
        if s >= char_pos:
            return idx
        if s < char_pos < e:
            return None
    return None


def _role_cue_names(text: str, spans: list[tuple[str, int, int]]) -> list[Entity]:
    ents: list[Entity] = []
    claimed: list[tuple[int, int]] = []
    for cue, vetoes in _ROLE_CUES:
        # O(occurrences) scan. The old `for pos in range(len(text))` header
        # re-ran text.find from every character position up to each match, so
        # one matched cue at offset P cost O(P^2) — measured as the dominant
        # share of the perf-gate pdf_redact regression once the cue list grew.
        search_from = 0
        while True:
            pos = text.find(cue, search_from)
            if pos == -1:
                break
            search_from = pos + 1
            cue_end = pos + len(cue)
            if any(pos < c_end and c_start < cue_end for c_start, c_end in claimed):
                continue
            after = text[cue_end : cue_end + 12]
            if "__require_space__" in vetoes:
                if not after[:1].isspace():
                    continue
            elif any(after.startswith(v) for v in vetoes):
                continue
            # optional linker/qualifier token(s) between cue and name
            idx = _index_after(spans, cue_end)
            if idx is None:
                continue
            skipped_qualifier = False
            while idx < len(spans):
                tok = spans[idx][0]
                if tok in _ROLE_QUALIFIERS:
                    skipped_qualifier = True
                elif not (tok in _ROLE_LINKERS or (tok.strip() == "" and "\n" not in tok)):
                    break
                idx += 1
            if idx < len(spans) and spans[idx][0] in _ORG_LEAD_TOKENS:
                continue
            got = _collect_two_groups(spans, idx)
            if got and skipped_qualifier and " " not in text[got[0] : got[1]]:
                # Stepping over a qualifier leaves it unmasked, so it must buy
                # a real two-group name; `_collect_two_groups` otherwise
                # returns a single-group span and "ผู้ป่วยหญิง อายุ 52 ปี"
                # would mint "อายุ" as a person.
                got = None
            if got:
                claimed.append((pos, got[1]))
                ents.append(_make_name(text, got[0], got[1], 0.88))
    return ents


def _line_label_names(text: str, spans: list[tuple[str, int, int]]) -> list[Entity]:
    ents = []
    for m in _LINE_NAME_LABEL_RE.finditer(text):
        idx = _index_after(spans, m.end())
        if idx is None:
            continue
        while idx < len(spans) and spans[idx][0].strip() == "":
            idx += 1
        if idx >= len(spans) or spans[idx][0] in _NON_PERSON_LEADS:
            continue
        got = _collect_two_groups(spans, idx)
        if got:
            ents.append(_make_name(text, got[0], got[1], 0.88))
    return ents


def _inline_label_names(text: str, spans: list[tuple[str, int, int]]) -> list[Entity]:
    ents = []
    for m in _INLINE_NAME_LABEL_RE.finditer(text):
        idx = _index_after(spans, m.end())
        if idx is None:
            continue
        while idx < len(spans) and spans[idx][0].strip() == "":
            idx += 1
        if idx >= len(spans) or spans[idx][0] in _NON_PERSON_LEADS:
            continue
        got = _collect_two_groups(spans, idx)
        if got:
            ents.append(_make_name(text, got[0], got[1], 0.87))
    return ents


def _kinship_label_names(text: str, spans: list[tuple[str, int, int]]) -> list[Entity]:
    ents = []
    for m in _KINSHIP_NAME_LABEL_RE.finditer(text):
        idx = _index_after(spans, m.end())
        if idx is None:
            continue
        got = _collect_two_groups(spans, idx)
        if got:
            ents.append(_make_name(text, got[0], got[1], 0.88))
    return ents


def _roster_names(text: str, spans: list[tuple[str, int, int]]) -> list[Entity]:
    ents = []
    for m in _ROSTER_CUE_RE.finditer(text):
        head_ctx = text[max(0, m.start() - _ROSTER_HEADER_WINDOW) : m.start()]
        if not _ROSTER_HEADER_RE.search(head_ctx):
            continue
        idx = _index_after(spans, m.end())
        if idx is None:
            continue
        while idx < len(spans) and spans[idx][0].strip() == "" and "\n" not in spans[idx][0]:
            idx += 1
        if idx >= len(spans) or spans[idx][0] in _ORG_LEAD_TOKENS:
            continue
        got = _collect_two_groups(spans, idx)
        if got:
            ents.append(_make_name(text, got[0], got[1], 0.87))
    return ents


# A Thai character immediately before a captured group means {2,25} clipped a
# longer run and the "name" starts mid-word.
_THAI_CHAR_RE = re.compile(r"[ก-๛]")


def _is_label_group(run: str) -> bool:
    """True when the run IS one form-label token, not merely led by one."""
    tokens = [t for t in word_tokenize(run, keep_whitespace=False) if t.strip()]
    return len(tokens) == 1 and is_non_person_segment(run)


def _passport_roster_names(text: str) -> list[Entity]:
    ents = []
    for m in _NAME_BEFORE_PASSPORT_RE.finditer(text):
        if not (_is_name_token(m.group(1)) and _is_name_token(m.group(2))):
            continue
        # `_is_name_token` does set membership on newmm TOKENS; these groups
        # are arbitrary <=25-char runs (a truncated document title, a field
        # label), which can never equal a stoplist token — the check is
        # vacuous on them. Two structural rejections replace it:
        #
        # 1. The first group must start at a WORD boundary. {2,25} silently
        #    clips a longer Thai run ("บันทึกการตรวจ..." -> "นทึกการตรวจ..."),
        #    and a name never begins mid-word — this is what actually
        #    separates the id02/id09 document titles from a roster row.
        # 2. A group is a label only when the label token IS the whole group.
        #    Judging the LEAD token alone made a prefix hit into evidence and
        #    unmasked a real compound surname (บัตรทอง -> บัตร|ทอง, the same
        #    "prefix is not evidence" rule trim_same_line_name_edges already
        #    documents; 2026-08-04 review).
        if m.start(1) > 0 and _THAI_CHAR_RE.match(text[m.start(1) - 1]):
            continue
        if _is_label_group(m.group(1)) or _is_label_group(m.group(2)):
            continue
        ents.append(_make_name(text, m.start(1), m.end(2), 0.88))
    return ents


def _latin_names(text: str) -> list[Entity]:
    ents = []
    seen: set[tuple[int, int]] = set()

    def _accept(m_start: int, value: str):
        parts = re.split(r"[ \t]+", value)
        if any(p.rstrip(".").lower() in _LATIN_ORG_STOP for p in parts):
            return
        span = (m_start, m_start + len(value))
        if span not in seen:
            seen.add(span)
            ents.append(_make_name(text, span[0], span[1], 0.88))

    for cue in _LATIN_CUE_RE.finditer(text):
        m = _LATIN_NAME_RE.match(text, cue.end())
        if m:
            _accept(m.start(), m.group(0))
    for m in _LATIN_TRAILING_PASSPORT_RE.finditer(text):
        _accept(m.start(1), m.group(1))
    return ents


def detect_name_context_passes(text: str) -> list[tuple[str, Entity]]:
    """All cue passes, tagged by provenance.

    "strong" passes (title/intro token pass, line-start name labels) are
    high-precision and always trusted. "extended" passes (roles, kinship,
    rosters, passport adjacency, Latin cues) were measured on the blind set to
    cost precision in registers gold does not cover (reveal 3), so the
    fine-tuned engine path keeps them only when the model agrees a person is
    there. The default CRF path keeps everything (recall-first).
    """
    if not text or not text.strip():
        return []

    spans = _token_spans(text)

    tagged: list[tuple[str, Entity]] = []
    tagged.extend(("extended", e) for e in _role_cue_names(text, spans))
    tagged.extend(("strong", e) for e in _line_label_names(text, spans))
    tagged.extend(("extended", e) for e in _inline_label_names(text, spans))
    tagged.extend(("extended", e) for e in _kinship_label_names(text, spans))
    tagged.extend(("extended", e) for e in _roster_names(text, spans))
    tagged.extend(("extended", e) for e in _passport_roster_names(text))
    tagged.extend(("extended", e) for e in _latin_names(text))
    tagged.extend(("strong", e) for e in _token_pass_names(text, spans))
    return tagged


def detect_name_context(text: str) -> list[Entity]:
    """Detect names introduced by a title, label, role word, or roster cue."""
    return [e for _pass, e in detect_name_context_passes(text)]


# A mid-sentence conjunction right after an accepted NAME introduces the NEXT
# person in the same list ("... เพ็ญศรี ทองอินทร์ และ ธงชัย รักถิ่นเกิด") --
# the CRF stops at และ, and no cue reaches a mid-sentence third name.
_CONJUNCTION_AFTER_NAME_RE = re.compile(r"[ \t]*(?:และ|กับ)[ \t]+")
# Wide enough for two 25-char name groups plus separators, small enough that
# tokenizing it is negligible next to a whole document.
_CONJUNCTION_WINDOW = 160


def detect_conjunction_names(text: str, entities: list[Entity]) -> list[Entity]:
    """Names introduced by และ/กับ directly after an already-accepted NAME.

    Two REAL groups are required (a space inside the collected span): the
    guard is load-bearing because `_collect_two_groups` returns a single-group
    span when the second group's head token is rejected, and "และ มารดา
    ของเด็ก" must not become a person.
    """
    seeds = [e for e in entities if e.data_type == "NAME"]
    if not seeds:
        return []
    ents: list[Entity] = []
    seen: set[tuple[int, int]] = set()
    for seed in seeds:
        m = _CONJUNCTION_AFTER_NAME_RE.match(text, seed.span[1])
        if m is None:
            continue
        # Tokenize only a bounded tail after the conjunction. A collected name
        # is at most two 25-char groups plus one separator, so the window
        # always contains it whole — and skipping the full-document
        # tokenization keeps this pass out of the detect hot path (it was
        # doubling the _token_spans cost of every detect call, measured on
        # the perf-gate fixture).
        window = text[m.end() : m.end() + _CONJUNCTION_WINDOW]
        spans = [(t, s + m.end(), e + m.end()) for t, s, e in _token_spans(window)]
        got = _collect_two_groups(spans, 0)
        if got is None or got in seen:
            continue
        if " " not in text[got[0] : got[1]]:
            continue
        seen.add(got)
        ents.append(_make_name(text, got[0], got[1], 0.87))
    return ents


_PARALLEL_NAME_LINE_RE = re.compile(r"^[ \t]*([ก-๛]{2,25})[ \t]+([ก-๛]{2,25})[ \t]*$")
_PARALLEL_NAME_STOP = _NOT_NAME | _LEAD_STOP | _NON_PERSON_LEADS
# The second Thai token is optional so the single-token shape keeps matching
# byte-for-byte, but a co-applicant written the normal way — given name, space,
# surname — is the common case on a real form and matched nothing before: the
# run between และ and the name may only hold non-Thai characters, so the space
# inside "สมหญิง รักดี" ended the name group early and the line failed. Missing
# a whole class of the names this rule exists to recover is the recall-negative
# direction, which recall > precision does not allow.
_OCR_CO_APPLICANT_RE = re.compile(
    r"(?m)^[ \t]*(?:และ|แถะ)[^ก-๛\r\n]{2,}"
    r"(?P<name>[ก-๛]{4,25}(?:[ \t]+[ก-๛]{2,25})?)[ \t]*$"
)
_OCR_CO_APPLICANT_STOP = (
    "กรอก",
    "ขอ",
    "คำ",
    "บริษัท",
    "ผู้",
    "มูลนิธิ",
    "เอกสาร",
    "โรงงาน",
    "โครงการ",
)


def _repeated_ocr_co_applicant_names(text: str, entities: list[Entity]) -> list[Entity]:
    """Find a name after an OCR form mark, repeated or alone on a 2-id record."""
    if sum(entity.data_type == "THAI_ID" for entity in entities) < 2:
        return []
    if not any(entity.data_type == "NAME" for entity in entities):
        return []

    matches = list(_OCR_CO_APPLICANT_RE.finditer(text))
    # A form carrying two checksum-valid national ids describes two people, so
    # the SINGLE co-applicant line on it is the second person -- requiring the
    # name to be REPEATED was a proxy for that evidence and rejected the real
    # คร.1 shape, which holds exactly one such line. The proxy stays in force
    # whenever the record structure is absent (the >=2 THAI_ID and >=1 NAME
    # gates above are unchanged).
    solitary = len(matches) == 1
    recovered = []
    for match in matches:
        value = match.group("name")
        if value.startswith(_OCR_CO_APPLICANT_STOP):
            continue
        repeated = any(
            other is not match and SequenceMatcher(None, value, other.group("name")).ratio() >= 0.8
            for other in matches
        )
        if repeated or solitary:
            recovered.append(_make_name(text, *match.span("name"), 0.87))
    return recovered


def detect_parallel_record_names(text: str, entities: list[Entity]) -> list[Entity]:
    """Recover a missed name in repeated NAME/THAI_ID rows."""
    recovered = _repeated_ocr_co_applicant_names(text, entities)
    rows: list[tuple[str, int, int]] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if stripped:
            start = offset + line.index(stripped)
            rows.append((stripped, start, start + len(stripped)))
        offset += len(raw_line)

    def _covered(row: tuple[str, int, int], data_type: str) -> bool:
        return any(
            entity.data_type == data_type and entity.span[0] <= row[1] and entity.span[1] >= row[2]
            for entity in entities
        )

    pairs: list[tuple[tuple[str, int, int], re.Match[str]]] = []
    for index, row in enumerate(rows[:-1]):
        match = _PARALLEL_NAME_LINE_RE.fullmatch(row[0])
        if match and _covered(rows[index + 1], "THAI_ID"):
            pairs.append((row, match))

    if not any(_covered(row, "NAME") for row, _match in pairs):
        return recovered

    for row, match in pairs:
        if _covered(row, "NAME"):
            continue
        if match.group(1) in _PARALLEL_NAME_STOP or match.group(2) in _PARALLEL_NAME_STOP:
            continue
        recovered.append(_make_name(text, row[1], row[2], 0.87))
    return recovered


def _token_pass_names(text: str, spans: list[tuple[str, int, int]]) -> list[Entity]:
    """The original token-level pass: titles and self-introduction labels."""
    ents: list[Entity] = []
    n = len(spans)
    for idx, (tok, _s, _e) in enumerate(spans):
        is_title = tok in _TITLES
        is_direct = tok in _DIRECT_NAME_CUES
        if is_direct:
            # A direct cue only introduces a NAME when a space follows it. Thai
            # runs words together, so "ข้าพเจ้าขอแสดงความนับถือ" (the standard
            # closing of an official letter) and "ข้าพเจ้ามีเลขบัตรประชาชน" tokenize
            # with the cue glued to the next word -- and the group collector
            # happily took "ขอแสดงความนับถือ" as a person's name and vaulted it.
            # Every verified false positive lacks the space; every real name
            # ("ข้าพเจ้า วิชัย ประสงค์ดี") has it.
            # ... except when the run glued to the cue is name-SHAPED under
            # `is_glued_name_run` (OCR deletes the space inside the name too:
            # "ข้าพเจ้า สมชาย ใจดี" came back as "ข้าพเจ้าสมชายใจดี"). The
            # single-dictionary-token rule there is what still rejects
            # "ข้าพเจ้าขอแสดงความนับถือ".
            nxt = spans[idx + 1][0] if idx + 1 < n else ""
            if nxt.strip() != "":
                glued = _GLUED_RUN_RE.match(text, spans[idx][2])
                if glued is not None and is_glued_name_run(glued.group(0)):
                    ents.append(_make_name(text, glued.start(), glued.end(), 0.88))
                continue
        is_cue = is_title or tok in _INTRO_COMPOUND or is_direct
        if not is_cue and tok == "ชื่อ":
            # cue only if the previous non-space token is a first-person pronoun
            j = idx - 1
            while j >= 0 and spans[j][0].strip() == "":
                j -= 1
            is_cue = j >= 0 and spans[j][0] in _PRONOUNS
        if not is_cue:
            continue

        # collect the name: first-name + optional surname (2 space-separated
        # groups). A single space joins the two groups; a second space ends it.
        # Thai first names often tokenize into several tokens, so count groups
        # (space gaps), not tokens.
        collected: list[tuple[int, int]] = []
        j = idx + 1
        space_seen = False
        while j < n:
            ttok, ts, te = spans[j]
            if ttok.strip() == "":  # whitespace
                if any(ch in ttok for ch in "\n\r") and collected:
                    # a name never spans a line break (mirror
                    # _collect_two_groups) -- the cue's vouching must not
                    # cross into the next physical line. Only once something
                    # has been collected, though: OCR of a form puts the label
                    # on its own line and the value on the next one
                    # ("ข้าพเจ้า\nวิชัย ประสงค์ดี"), and breaking on that
                    # leading newline left the name unmasked entirely.
                    break
                if not collected:  # leading space (or line break) before the name
                    j += 1
                    continue
                if space_seen:  # second gap -> first+surname already captured
                    break
                space_seen = True
                j += 1
                continue
            if _is_name_token(ttok):
                collected.append((ts, te))
                j += 1
            else:
                break

        if collected:
            # for a title cue, include the title in the span so this fuller
            # entity wins de-duplication against a CRF hit that clipped the
            # surname (e.g. CRF "นายสมชาย" vs here "นายสมชาย ใจดี").
            start = spans[idx][1] if is_title else collected[0][0]
            end = collected[-1][1]
            # A collected value that IS a document compound is a header the
            # cue accidentally vouched for ("สถานีตำรวจภูธรเมือง" after the
            # doc-title token ผู้เสียหาย) -- the rejection list already
            # exists; consult it. Judged on the name part sans title so a
            # real "นาย <name>" span cannot self-reject.
            if _NAME_DOC_COMPOUND_RE.match(text[collected[0][0] : end]):
                continue
            if end - start >= 2:  # span chokepoint
                ents.append(
                    Entity(
                        entity_id=str(uuid.uuid4()),
                        redact_type="TB",
                        data_type="NAME",
                        span=(start, end),
                        score=0.9,
                        original_text=text[start:end],
                    )
                )
    return ents
