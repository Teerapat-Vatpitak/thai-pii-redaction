"""Hand-authored Thai PII gold set (v2).

Realistic, un-templated Thai documents with fake PII, labeled inline with
[[TYPE|value]] markup that parse_gold() converts to exact-span Samples. This
targets v1's blind spots: names without title cues, addresses in many real
forms, messy real-world formatting, and the BANK-vs-PHONE ambiguity. All PII is
fake (privacy-safe): the checksum-bearing values (THAI_ID, CREDIT_CARD) were
generated valid, the rest are plausible fabrications.

Gold is a DIAGNOSTIC -- it exists to expose where recall drops, not to be
gated to green.
"""
from __future__ import annotations

import re

from .types import GoldSpan, Sample

GOLD_SLICES = ["name_no_cue", "address_varied", "messy", "bank_phone"]

_MARKUP = re.compile(r"\[\[([A-Z_]+)\|(.*?)\]\]")


def parse_gold(doc_id: str, slice_: str, annotated: str) -> Sample:
    parts: list[str] = []
    spans: list[GoldSpan] = []
    pos = 0
    out_len = 0
    for m in _MARKUP.finditer(annotated):
        pre = annotated[pos:m.start()]
        parts.append(pre)
        out_len += len(pre)
        etype, value = m.group(1), m.group(2)
        start = out_len
        parts.append(value)
        out_len += len(value)
        spans.append(GoldSpan(start, out_len, etype))
        pos = m.end()
    parts.append(annotated[pos:])
    return Sample(text="".join(parts), spans=spans, template_id=doc_id, slice=slice_)


# (doc_id, slice, annotated_text)
GOLD_DOCS: list[tuple[str, str, str]] = [
    # ── name_no_cue: names with NO นาย/นาง/นางสาว/ลงชื่อ/ผมชื่อ cue ──────────
    ("nc01", "name_no_cue", "ผู้จัดการฝ่ายขาย [[NAME|วิชัย ประสงค์ดี]] อนุมัติใบเบิกเงินเรียบร้อยแล้ว"),
    ("nc02", "name_no_cue", "ที่ประชุมมอบหมายให้ [[NAME|กานดา สุขเกษม]] เป็นผู้ดำเนินการแทน"),
    ("nc03", "name_no_cue", "ติดต่อ [[NAME|ธนา รักษาสัตย์]] ฝ่ายบุคคล เพื่อยื่นเอกสารเพิ่มเติม"),
    ("nc04", "name_no_cue", "รายชื่อกรรมการ 1. [[NAME|อรทัย มีทรัพย์]] 2. [[NAME|ประเสริฐ ทองใบ]] 3. [[NAME|สุนิสา วงศ์ไทย]]"),
    ("nc05", "name_no_cue", "โครงการนี้ริเริ่มโดย [[NAME|ภาณุพงศ์ เจริญพร]] และทีมงานวิจัย"),
    ("nc06", "name_no_cue", "( [[NAME|สุดารัตน์ พูนผล]] )\nตำแหน่ง ผู้อำนวยการสำนักงาน"),
    ("nc07", "name_no_cue", "หัวหน้าโครงการ [[NAME|กิตติศักดิ์ ชัยมงคล]] รายงานผลการดำเนินงานประจำไตรมาส"),
    ("nc08", "name_no_cue", "แพทย์ผู้ตรวจ [[NAME|พิมพ์ใจ รุ่งเรือง]] ลงความเห็นให้พักรักษาตัว 3 วัน"),
    ("nc09", "name_no_cue", "ผู้เสียหายคือ [[NAME|อนุชา ดวงแก้ว]] แจ้งความไว้เป็นหลักฐาน"),
    ("nc10", "name_no_cue", "อาจารย์ที่ปรึกษา [[NAME|วรรณา ศรีสุข]] ได้ตรวจสอบวิทยานิพนธ์แล้ว"),
    ("nc11", "name_no_cue", "พยานในที่เกิดเหตุ ได้แก่ [[NAME|สมพร ใจซื่อ]] กับ [[NAME|ณัฐพล บุญมาก]]"),
    ("nc12", "name_no_cue", "คำสั่งแต่งตั้ง [[NAME|ชนิดา ทิพย์มณี]] ให้รักษาการหัวหน้าแผนกการเงิน"),
    ("nc13", "name_no_cue", "ผู้รับมอบอำนาจ [[NAME|เกษม สายทอง]] ดำเนินการโอนกรรมสิทธิ์ที่ดิน"),
    ("nc14", "name_no_cue", "ลูกค้า [[NAME|มาลี พฤกษ์งาม]] ร้องเรียนเรื่องบริการล่าช้าผ่านศูนย์รับเรื่อง"),
    ("nc15", "name_no_cue", "ผู้ยื่นอุทธรณ์ [[NAME|ปรีชา หาญกล้า]] ขอให้ทบทวนคำวินิจฉัยอีกครั้ง"),
    ("nc16", "name_no_cue", "เจ้าของกิจการ [[NAME|รุ่งนภา เพชรน้ำหนึ่ง]] จดทะเบียนพาณิชย์เมื่อปีที่แล้ว"),
    ("nc17", "name_no_cue", "ผู้ค้ำประกันเงินกู้คือ [[NAME|สราวุธ มั่นคง]] ตามสัญญาแนบท้าย"),
    ("nc18", "name_no_cue", "คนไข้ [[NAME|จันทร์เพ็ญ ดีงาม]] เข้ารับการผ่าตัดตามนัดหมายของแพทย์"),

    # ── address_varied: addresses in many real Thai forms ─────────────────
    ("ad01", "address_varied", "จัดส่งพัสดุไปที่ [[ADDRESS|บ้านเลขที่ 45/12 หมู่ 3 ตำบลบางพระ อำเภอศรีราชา จังหวัดชลบุรี 20110]]"),
    ("ad02", "address_varied", "ที่อยู่ตามบัตรประชาชน [[ADDRESS|99 ซอยลาดพร้าว 71 ถนนลาดพร้าว แขวงวังทองหลาง เขตวังทองหลาง กรุงเทพมหานคร 10310]]"),
    ("ad03", "address_varied", "สถานที่ตั้งสำนักงาน [[ADDRESS|เลขที่ 1010 อาคารชินวัตร ถนนพหลโยธิน แขวงจอมพล เขตจตุจักร กทม. 10900]]"),
    ("ad04", "address_varied", "ภูมิลำเนาเดิม [[ADDRESS|บ้านเลขที่ 7 หมู่ที่ 9 ต.แม่เหียะ อ.เมือง จ.เชียงใหม่]]"),
    ("ad05", "address_varied", "โปรดจัดส่งเอกสารมายัง [[ADDRESS|123/456 คอนโดริเวอร์ไซด์ ชั้น 12 ถนนเจริญนคร คลองต้นไทร คลองสาน กรุงเทพฯ]]"),
    ("ad06", "address_varied", "ที่อยู่ปัจจุบัน [[ADDRESS|88 หมู่บ้านสวนหลวง ซอย 4 ตำบลหนองปรือ อำเภอบางละมุง ชลบุรี 20150]]"),
    ("ad07", "address_varied", "สาขาที่ให้บริการ [[ADDRESS|เลขที่ 200 ถนนนิมมานเหมินท์ ตำบลสุเทพ อำเภอเมืองเชียงใหม่ 50200]]"),
    ("ad08", "address_varied", "ส่งใบแจ้งหนี้ไปที่ [[ADDRESS|55/1 ถนนสุขุมวิท ซอย 24 คลองตัน คลองเตย กรุงเทพมหานคร]]"),
    ("ad09", "address_varied", "ที่ทำการไปรษณีย์ปลายทาง [[ADDRESS|หมู่ 5 บ้านโนนสูง ตำบลในเมือง อำเภอเมือง จังหวัดนครราชสีมา 30000]]"),
    ("ad10", "address_varied", "โรงงานตั้งอยู่ที่ [[ADDRESS|นิคมอุตสาหกรรมอมตะนคร 700/1 หมู่ 6 ตำบลดอนหัวฬ่อ อำเภอเมือง ชลบุรี]]"),
    ("ad11", "address_varied", "ที่อยู่จัดส่ง [[ADDRESS|29 ถนนราชดำเนิน ตำบลตลาด อำเภอเมือง จังหวัดนครศรีธรรมราช 80000]]"),
    ("ad12", "address_varied", "สำเนาทะเบียนบ้าน [[ADDRESS|บ้านเลขที่ 312/7 ซอยเพชรเกษม 48 แขวงบางด้วน เขตภาษีเจริญ กทม. 10160]]"),
    ("ad13", "address_varied", "ร้านตั้งอยู่ [[ADDRESS|เลขที่ 15 ตลาดสดเทศบาล ถนนศรีจันทร์ อำเภอเมือง ขอนแก่น]]"),
    ("ad14", "address_varied", "หอพักนักศึกษา [[ADDRESS|9/99 ซอยมหาวิทยาลัย ตำบลคลองหก อำเภอคลองหลวง ปทุมธานี 12120]]"),
    ("ad15", "address_varied", "ที่อยู่เพื่อออกใบกำกับภาษี [[ADDRESS|เลขที่ 456 หมู่ 2 ถนนมิตรภาพ ตำบลปากช่อง อำเภอปากช่อง นครราชสีมา 30130]]"),
    ("ad16", "address_varied", "ส่งของไปบ้าน [[ADDRESS|17 ซอยอ่อนนุช 17 แยก 3 สวนหลวง กรุงเทพฯ 10250]] ฝากไว้หน้าบ้านได้"),

    # ── messy: glued PII, odd spacing, Thai-English labels, multiline ──────
    ("ms01", "messy", "ผู้ติดต่อ[[NAME|มานพ ดีเลิศ]]เบอร์[[PHONE|0891234567]]อีเมล[[EMAIL|manop.d@example.com]]"),
    ("ms02", "messy", "Tel: [[PHONE|0812345678]]   E-mail: [[EMAIL|jane.doe@company.co.th]]"),
    ("ms03", "messy", "ชื่อ [[NAME|กมล ทวีสิน]]\nโทร [[PHONE|0955512340]]\nที่อยู่ [[ADDRESS|12 ถนนสุขุมวิท กทม.]]"),
    ("ms04", "messy", "เลขบัตร[[THAI_ID|8107583270701]]ออกให้ ณ อำเภอเมือง"),
    ("ms05", "messy", "ข้อมูลผู้สมัคร:Name=[[NAME|Somsak Jaidee]],ID=[[THAI_ID|2140527002190]],Tel=[[PHONE|0623456789]]"),
    ("ms06", "messy", "ติดต่อกลับที่ [[EMAIL|support_team@mail.example.org]] หรือ line id เดียวกัน"),
    ("ms07", "messy", "บัตรเครดิตหมายเลข [[CREDIT_CARD|5292-9524-0865-2921]] หมดอายุ 08/28"),
    ("ms08", "messy", "ผู้ป่วยชื่อ[[NAME|วิภาวดี นครชัย]]HN12345เข้ารับการรักษาแผนกอายุรกรรม"),
    ("ms09", "messy", "โทรศัพท์:[[PHONE|021234567]]/แฟกซ์:[[PHONE|021234568]]"),
    ("ms10", "messy", "email :   [[EMAIL|k.watchara@bank.example.com]]   วันเกิด [[DATE_OF_BIRTH|14/02/2535]]"),
    ("ms11", "messy", "ทะเบียนรถ[[VEHICLE_PLATE|ขก 4471]]จอดในลานจอด B2 ช่องที่ 15"),
    ("ms12", "messy", "รหัสนักศึกษา[[STUDENT_ID|64010812]]คณะวิศวกรรมศาสตร์ ชั้นปีที่ 3"),
    ("ms13", "messy", "หนังสือเดินทางเลขที่[[PASSPORT|AB1234567]]ออกโดยกรมการกงสุล"),
    ("ms14", "messy", "แจ้งโอนเงินมาที่ [[NAME|เอกชัย พรพนา]] ปลายทาง [[PHONE|0987654321]] ด่วนภายในวันนี้"),
    ("ms15", "messy", "contact person [[NAME|Nattaya S.]] mobile [[PHONE|0644445555]] office 02-555-1234"),
    ("ms16", "messy", "ผู้รับเงิน [[NAME|บุญเลิศ ทรัพย์ทวี]]  เลขที่บัญชี [[BANK_ACCOUNT|1234567890]]  ธ.ออมสิน"),

    # ── bank_phone: 10-digit numbers starting 06-09 with disambiguating cue ─
    ("bp01", "bank_phone", "เลขที่บัญชี [[BANK_ACCOUNT|0612345678]] ธนาคารกรุงเทพ สาขาสีลม"),
    ("bp02", "bank_phone", "โทร [[PHONE|0612345678]] เพื่อสอบถามรายละเอียดเพิ่มเติม"),
    ("bp03", "bank_phone", "โอนเข้าบัญชีเลขที่ [[BANK_ACCOUNT|0898765432]] ชื่อบัญชีบริษัทตัวอย่างจำกัด"),
    ("bp04", "bank_phone", "เบอร์มือถือติดต่อ [[PHONE|0898765432]] ได้ตลอด 24 ชั่วโมง"),
    ("bp05", "bank_phone", "บัญชีธนาคารกสิกรไทย เลขที่ [[BANK_ACCOUNT|0731122334]] พร้อมสลิปยืนยัน"),
    ("bp06", "bank_phone", "ติดต่อเจ้าหน้าที่ที่เบอร์ [[PHONE|0731122334]] ในเวลาทำการ"),
    ("bp07", "bank_phone", "ชำระเงินโดยโอนเข้าบัญชี [[BANK_ACCOUNT|0655667788]] แล้วส่งหลักฐานกลับมา"),
    ("bp08", "bank_phone", "หากมีข้อสงสัยโทรหาฝ่ายบริการลูกค้า [[PHONE|0655667788]]"),
    ("bp09", "bank_phone", "เลขบัญชีสำหรับรับเงินคืน [[BANK_ACCOUNT|0944332211]] ธนาคารไทยพาณิชย์"),
    ("bp10", "bank_phone", "มือถือของผู้จัดการคือ [[PHONE|0944332211]] ฝากข้อความได้"),
    ("bp11", "bank_phone", "กรุณาโอนมายังบัญชี [[BANK_ACCOUNT|0812009900]] ภายในสามวันทำการ"),
    ("bp12", "bank_phone", "เบอร์ [[PHONE|0812009900]] เป็นสายตรงถึงแผนกจัดซื้อ"),
    ("bp13", "bank_phone", "ยอดค้างชำระโอนเข้าเลขที่บัญชี [[BANK_ACCOUNT|0778001234]] ด่วน"),
    ("bp14", "bank_phone", "ติดต่อ [[PHONE|0778001234]] แผนกทวงถามหนี้สิน"),
    ("bp15", "bank_phone", "บัญชีปลายทาง [[BANK_ACCOUNT|0690011223]] สำหรับค่ามัดจำสินค้า"),
    ("bp16", "bank_phone", "โทรกลับด่วนที่ [[PHONE|0690011223]] ก่อนสิบเจ็ดนาฬิกา"),
]


def load_gold() -> list[Sample]:
    return [parse_gold(doc_id, slice_, text) for doc_id, slice_, text in GOLD_DOCS]
