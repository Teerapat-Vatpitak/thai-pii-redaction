# NER engine strategy decision — ADR จาก 4-way benchmark comparison

- สถานะ ตัดสินแล้ว
- วันที่ 2026-07-15

เอกสารนี้คือ ADR (architecture decision record) บันทึกการตัดสิน NER engine strategy จากผลวัด 4 กลยุทธ์ (crf / wcb / union / route) บน benchmark จริงทั้ง gold และ synthetic

## บริบท

เอกสารที่เกี่ยวข้อง [NER engine strategy comparison design](2026-07-15-ner-engine-strategy-comparison-design.md), [gold v2 benchmark design](2026-07-14-thai-pii-recall-benchmark-gold-v2-design.md), [production tech-stack selection design](2026-07-13-production-tech-stack-selection-design.md)

stack-selection doc (2026-07-13) แนะนำเปลี่ยน NER หลักเป็น WangchanBERTa (thainer-v2) เป็น primary อ้างตัวเลข ThaiNER PERSON recall 0.79 ไป 0.95 (LOCATION 0.68 ไป 0.88) เป็นหลักฐานว่า transformer เหนือ CRF ชัดเจนสำหรับ product ที่ recall สำคัญกว่า precision

gold v2 (2026-07-14) วัดของเราเองแล้วเจอตรงข้ามบางส่วน บน NAME ที่ไม่มี title cue (นาย/นาง/นางสาว) WangchanBERTa recall เหลือ 0.357 แพ้ CRF ที่ 0.607 เพราะตัวเลขที่ stack-selection doc อ้างเป็น in-distribution ที่ใส่ title cue ครบ พอถอด cue ออกภาพจริงต่าง ส่วน ADDRESS WangchanBERTa ยังชนะ CRF (1.000 เทียบ 0.882) ตรงกับที่ stack-selection doc คาด

ความขัดแย้งนี้แปลว่าตัดสิน engine เดี่ยวไม่ได้ ต้องวัด union (CRF ∪ WCB) และ route-by-type (NAME จาก CRF, ADDRESS จาก WCB) เพิ่ม ซึ่งเป็นเป้าหมายของงานนี้ เอกสารนี้คือผลลัพธ์หลังรันจริงทั้ง 4 กลยุทธ์บนทั้งสอง corpus

## ตารางผล gold

รัน `python -m benchmark --compare-strategies --source gold` (seed 42, size 200, corpus จริง 66 samples / 81 entities)

recall ต่อชนิด (คอลัมน์ = crf / wcb / union / route)

| ชนิด | crf | wcb | union | route |
|---|---|---|---|---|
| ADDRESS | 0.882 | 1.000 | 1.000 | 1.000 |
| BANK_ACCOUNT | 1.000 | 1.000 | 1.000 | 1.000 |
| CREDIT_CARD | 1.000 | 1.000 | 1.000 | 1.000 |
| DATE_OF_BIRTH | 1.000 | 1.000 | 1.000 | 1.000 |
| EMAIL | 1.000 | 1.000 | 1.000 | 1.000 |
| NAME | 0.607 | 0.357 | 0.643 | 0.607 |
| PASSPORT | 1.000 | 1.000 | 1.000 | 1.000 |
| PHONE | 0.875 | 0.875 | 0.875 | 0.875 |
| STUDENT_ID | 1.000 | 1.000 | 1.000 | 1.000 |
| THAI_ID | 1.000 | 1.000 | 1.000 | 1.000 |
| VEHICLE_PLATE | 1.000 | 1.000 | 1.000 | 1.000 |

overall ต่อกลยุทธ์

| metric | crf | wcb | union | route |
|---|---|---|---|---|
| OVERALL recall | 0.815 | 0.753 | 0.852 | 0.840 |
| OVERALL precision | 0.635 | 0.629 | 0.616 | 0.667 |
| coverage | 0.669 | 0.642 | 0.740 | 0.686 |

per-slice recall (name_no_cue และ address_varied มาจาก JSON `by_slice` ต่อกลยุทธ์)

| slice | crf | wcb | union | route |
|---|---|---|---|---|
| name_no_cue | 0.714 | 0.381 | 0.714 | 0.714 |
| address_varied | 0.875 | 1.000 | 1.000 | 1.000 |

## ตารางผล synthetic

รัน `python -m benchmark --compare-strategies --source synthetic --seed 42 --size 200`

recall ต่อชนิด (คอลัมน์ = crf / wcb / union / route)

| ชนิด | crf | wcb | union | route |
|---|---|---|---|---|
| ADDRESS | 0.594 | 1.000 | 1.000 | 1.000 |
| BANK_ACCOUNT | 1.000 | 1.000 | 1.000 | 1.000 |
| CREDIT_CARD | 1.000 | 1.000 | 1.000 | 1.000 |
| DATE_OF_BIRTH | 1.000 | 1.000 | 1.000 | 1.000 |
| EMAIL | 1.000 | 1.000 | 1.000 | 1.000 |
| NAME | 0.994 | 0.994 | 0.994 | 0.994 |
| PASSPORT | 1.000 | 1.000 | 1.000 | 1.000 |
| PHONE | 1.000 | 1.000 | 1.000 | 1.000 |
| STUDENT_ID | 1.000 | 1.000 | 1.000 | 1.000 |
| THAI_ID | 1.000 | 1.000 | 1.000 | 1.000 |
| VEHICLE_PLATE | 1.000 | 1.000 | 1.000 | 1.000 |

overall ต่อกลยุทธ์

| metric | crf | wcb | union | route |
|---|---|---|---|---|
| OVERALL recall | 0.977 | 0.998 | 0.998 | 0.998 |
| OVERALL precision | 0.923 | 0.916 | 0.900 | 0.916 |
| coverage | 0.942 | 0.961 | 0.971 | 0.961 |

synthetic ใช้ slice `core` / `hard_case` ไม่ใช่ `name_no_cue` / `address_varied` (สอง slice นั้นมีเฉพาะใน gold) จึงไม่มีตารางเทียบ slice เดียวกันสำหรับ synthetic

## การตัดสิน

เลือกกลยุทธ์ `union` (CRF ∪ WCB รวม span ทั้งคู่ dedup)

เหตุผลผูกกับ invariant recall มากกว่า precision และดูจาก gold ซึ่งเป็น corpus จริง (diagnostic) ไม่ใช่ synthetic ที่ทุก entity ถูกสร้างให้จับง่าย

บน gold union เป็นกลยุทธ์เดียวที่กด NAME recall สูงสุด (0.643) พร้อมกันกับ ADDRESS recall สูงสุด (1.000) ในเวลาเดียวกัน route ได้ ADDRESS 1.000 เท่ากันแต่ NAME ตกกลับไปเท่า crf เดี่ยว (0.607) เพราะ route ดึง NAME จาก CRF ล้วน ไม่ยืมจาก WCB เลย ส่วน wcb เดี่ยวแม้ ADDRESS เต็ม 1.000 แต่ NAME ร่วงเหลือ 0.357 ต่ำสุดในสี่กลยุทธ์ union จึงเป็นกลยุทธ์เดียวที่ maximise ทั้งสองชนิดพร้อมกัน ไม่ใช่แค่ชนิดใดชนิดหนึ่ง

union ยังให้ OVERALL recall สูงสุดบน gold (0.852 เทียบ crf 0.815 wcb 0.753 route 0.840) และ coverage สูงสุด (0.740) ราคาที่จ่ายคือ OVERALL precision ต่ำสุด (0.616 เทียบ route 0.667) ซึ่งตรงกับสิ่งที่ invariant recall มากกว่า precision ยอมรับได้ ยอม false positive เพิ่มขึ้นเพื่อไม่พลาด PII จริง

บน synthetic union เสมอกับ wcb และ route ที่ recall สูงสุดเท่ากันทุกชนิด (NAME 0.994 ADDRESS 1.000 OVERALL 0.998) จึง synthetic ไม่ใช่ตัวชี้ขาด เพราะ corpus นี้ไม่มี case ที่ทำให้ engine ต่างกันชัดเหมือน gold แต่ union ยังคง coverage สูงสุด (0.971) แม้ precision ต่ำสุด (0.900) เช่นเดิม สอดคล้องทิศทางเดียวกับผล gold

## Trade-off

- crf เร็วที่สุด (offline ~1-5 ms/ประโยค) แต่ recall ต่ำสุดในภาพรวม gold (OVERALL_R 0.815) โดยเฉพาะ ADDRESS (0.882)
- wcb ยก ADDRESS recall เต็ม 1.000 แต่ทิ้ง NAME-ไม่มี-cue รุนแรง (0.357 บน gold slice name_no_cue 0.381)
- union recall สูงสุดทั้ง NAME และ ADDRESS พร้อมกัน แลกกับ precision ต่ำสุด (gold 0.616 synthetic 0.900) และต้องรัน 2 engine ต่อ sample
- route สมดุลกว่า union ด้าน precision (gold 0.667) แต่ NAME ไม่ได้ประโยชน์จาก WCB เลย (เท่า crf เดี่ยว) และยังต้องรัน 2 engine เหมือน union

union และ route จ่ายต้นทุน WangchanBERTa เท่ากับ wcb เดี่ยว (~1.3 วินาที/ประโยคบน CPU torch) เพราะทั้งคู่ต้องรันทั้ง 2 engine ต่อ sample เสมอ ไม่ใช่แค่เมื่อ route ไปทาง WCB latency นี้ไม่ได้ถูกวัดในโค้ด benchmark (scorer วัดเฉพาะ recall/precision) แต่เป็นต้นทุนที่ทราบจาก stack-selection doc

## Reconcile กับ stack-selection doc

คำแนะนำเดิมของ stack-selection doc (WCB เป็น primary เดี่ยว) ไม่ยืนตามที่เขียนไว้ ตัวเลข PERSON 0.79 ไป 0.95 ที่ doc อ้างเป็น in-distribution (มี title cue ครบ) ไม่ generalize ไปยัง NAME ที่ไม่มี cue ซึ่ง gold วัดได้จริงว่า WCB ตกเหลือ 0.357

การตัดสินใหม่คือ union ไม่ใช่ WCB เดี่ยว และไม่ใช่ CRF เดี่ยวตามเดิมด้วย ส่วนที่ stack-selection doc พูดถูกคือ ADDRESS ควรใช้ WCB (union ครอบคลุมส่วนนี้อยู่แล้วเพราะรวม span ทั้งคู่) แต่ส่วนที่ doc พูดไม่ครบคือ NAME ไม่ควรทิ้ง CRF ไปทั้งหมด union แก้จุดนี้โดยไม่ต้องเลือกทิ้งฝั่งใดฝั่งหนึ่ง

## นัยต่อ Rust rewrite

union บังคับแบก 2 engine พร้อมกันที่ inference time (CRF และ WangchanBERTa) ต่างจากแผนเดิมในADR/stack doc ที่คิดว่าจะ pin WCB เป็น primary เดี่ยวแล้วผ่อน CRF เป็น first-pass tier เฉยๆ

กระทบแผน ort/ONNX ในสอง stack-selection doc ตรงที่ Rust rewrite ต้อง serve ทั้ง CRF (เบา offline) และ WangchanBERTa ผ่าน ort พร้อมกัน ไม่ใช่แค่ WangchanBERTa ตัวเดียว เพิ่มความซับซ้อนของ binding และ memory footprint เทียบกับแผน WCB-primary เดี่ยวเดิม แต่ยังอยู่ในทิศทางที่ stack-selection doc เลือกไว้แล้ว (ort ไม่ใช่ candle เพราะ WangchanBERTa เป็น RoBERTa ที่ candle ไม่มี head รองรับ) จุดที่เปลี่ยนคือขอบเขตงาน ไม่ใช่เทคโนโลยีที่เลือก

## สิ่งที่ยังไม่ทำ

การ implement กลยุทธ์ union ใน `detect_tb`/`detect_all` จริงเป็นงานแยกต่างหาก ต้องผ่าน spec ไป plan ไป implement คนละรอบ งานนี้เป็นแค่การวัดและตัดสินใจ ไม่แตะ product code

weighted-vote, confidence-gate, CRF-first-then-WCB-fallback ไม่ได้ถูกวัดในงานนี้ เป็นทางเลือกที่อาจเสนอทีหลังถ้ามีเหตุผลว่า union ธรรมดายังไม่พอ
