# Production tech-stack selection — AI Guard (recall-first)

- วันที่ 2026-07-13
- บริบท ผู้ใช้ถามว่าถ้าอยากให้ระบบใช้งานจริงได้ ไม่ใช่แค่ผ่านการประกวด ควรเลือกใช้อะไร เอาแบบดีที่สุดพร้อมสถิติเทียบ เอกสารนี้คือข้อเสนอเลือกสแตกต่อแกนการตัดสินใจ อ้างอิงงานวิจัยที่ค้นจริง
- เอกสารที่เกี่ยวข้อง [rust rewrite architecture](2026-07-10-rust-rewrite-architecture-design.md) (แผน rewrite เดิมที่เอกสารนี้ท้าทายบางจุด), [post-competition roadmap](2026-07-10-post-competition-longterm-roadmap.md), [aiguard-core detection plan](../plans/2026-07-10-aiguard-core-detection.md)
- ที่มา สังเคราะห์จาก workflow วิจัย 7 research agent ค้นเว็บแบบขนาน (wf_d495f615-b16) แต่ละแกนหาสถิติจาก primary source (arXiv/ACL, HuggingFace model card, GitHub, leaderboard)
- สถานะ ข้อเสนอ ยังไม่ตัดสิน รอผู้ใช้เลือก
- คงเดิม product ทำอะไรและ data flow ไม่เปลี่ยน invariant recall มากกว่า precision และ vault ห้ามออกเครื่องยังอยู่ครบ

## คำเตือนสำคัญก่อนอ่านตัวเลข

- F1 ของ Thai NER ทั่วไป ไม่ใช่ recall ของ PII structured PII (ID phone email bank card passport) จับด้วย FP regex+checksum ไม่ใช่ NER โมเดลเพิ่ม recall เฉพาะ PERSON/LOCATION/ORG ให้ตัดสินด้วย per-class recall ของสองชนิดนั้น ไม่ใช่ headline micro-F1
- ยังไม่มี benchmark PII ภาษาไทยสาธารณะเลย AI4Privacy (200k/300k/500k/2M) และ paper 13-locale ตัดไทยออกทั้งหมด ตัวเลข Thai NER ที่มี (ThaiNER/LST20) เป็น general NER ไม่ใช่ PII-labeled ตัวเลขเด่นๆ ในเอกสารนี้ส่วนใหญ่จึงเป็น proxy ต้องวัดกับข้อมูลไทยของตัวเองก่อนเชื่อ
- ตัวเลข vendor เป็น in-distribution ที่ overstate จริง (Piiranha 98.27% กลายเป็น cross-domain ~0.54) ตัวเลข lab เป็นข่าวทางการ ข้อมูลจริงเป็นแชท/ฟอร์ม/OCR ที่ out-of-distribution ให้เผื่อ recall จริงต่ำกว่าหลาย point

## สามคำตัดสินที่สำคัญที่สุด

1. เปลี่ยน NER หลักจาก thainer-CRF เป็น WangchanBERTa fine-tuned (thainer-v2) หลักฐานชัดสำหรับ product ที่ recall สำคัญกว่า precision recall ชื่อคน 0.79 ไป 0.95 ที่อยู่ 0.68 ไป 0.88 และตัวนี้อยู่ในโค้ดแล้ว (opt-in AIGUARD_NER_ENGINE=wangchanberta)
2. อย่าเดิมพัน core NER ไว้กับ candle แผน rewrite ปัจจุบันวางผิดจุด ถ้าจะไป Rust ใช้ ort (ONNX Runtime) หรือทางเสี่ยงต่ำสุดคืออยู่ Python ต่อแล้วสลับ torch เป็น onnxruntime
3. สร้าง benchmark recall PII ภาษาไทยก่อนตัดสินใจ rewrite ทุกอย่าง ตอนนี้ไม่มีตัวเลข recall PII ไทยจริงมา gate การตัดสินใจเลย

## 1 สแตกที่แนะนำ หนึ่งหน้า

| แกน | ที่แนะนำ | ทำไม | ตัวสำรอง |
|---|---|---|---|
| NER free-text (ชื่อ ที่อยู่) | WangchanBERTa fine-tuned (thainer-v2) เป็น primary | recall PERSON 0.79 ไป 0.95 LOCATION 0.68 ไป 0.88 offline CPU และมีในโค้ดแล้ว | CRF เป็น first-pass tier เร็ว หรือ XLM-R-base ถ้าต้องรับไทยปนอังกฤษ |
| zero-shot / LLM เสริม | GLiNER multilingual เป็น recall net ไม่ใช่ตัวหลัก | ไม่มี zero-shot ตัวไหนมี recall PII ไทยตีพิมพ์ GPT-4o zero-shot recall แค่ 0.44 | NuNER Zero เฉพาะ path อังกฤษ |
| OCR สแกน | PaddleOCR PP-OCRv5 (th) คงไว้ | ตัวเดียวที่ครบ โมเดลไทย + box จริง + ~10MB + Apache-2.0 + มี Rust path | PaddleOCR-VL ผ่าน candle เป็น ceiling EasyOCR เป็น cross-check |
| PDF extract + redact | PDFium ทั้งสอง stack pypdfium2 แล้วพอร์ตเป็น pdfium-render | engine เดียวกัน fidelity ไทยและ box carry over ทันที คง flatten-to-image | pdfplumber เฉพาะ prototype Python |
| Tokenizer | nlpo3 (Rust port ของ newmm) | ตัวเดียวที่ mature offline Rust Apache-2.0 ไทยล้วน identical กับ newmm | nlpo3 + Deepcut feature สำหรับข้อความ social |
| inference / backend | ort (ONNX Runtime) + int8 หลัง axum | รัน RoBERTa จริงได้ int8 speedup ขี่ runtime ของ Microsoft | อยู่ Python ต่อ FastAPI + onnxruntime + optimum เสี่ยงต่ำสุด |
| architecture + eval | คง ensemble เดิม ยืม presidio-evaluator เป็น harness | สถาปัตย์ตรง best-practice อยู่แล้ว และมี leak-guard ที่ Presidio ไม่มี | ยืม Presidio เป็น reference เฉย ไม่ re-platform |

บรรทัดเดียวที่สำคัญที่สุด ต้องสร้าง benchmark PII ภาษาไทย (synthetic + gold set เล็กจากเอกสารจริง) ก่อนตัดสินใจ rewrite ทุกอย่าง

## 2 ทีละแกนพร้อมตารางสถิติ

### แกน 1 Thai NER encoder บนเครื่อง

| โมเดล | metric + dataset | params / size | latency CPU | license | ความเสี่ยง |
|---|---|---|---|---|---|
| thainer-CRF (ปัจจุบัน) | micro-F1 0.790 R 0.741 PERSON R 0.794 LOCATION R 0.677 (ThaiNER v1.3 seqeval) | ~ไม่กี่ MB | ~1-5 ms/ประโยค | Apache-2.0 corpus CC-BY-3.0 | recall ต่ำ พลาด ~1 ใน 4 entity ~1 ใน 3 ที่อยู่ ผิด invariant ถ้าใช้เดี่ยว |
| WangchanBERTa base | micro-F1 0.865 R 0.888 PERSON R 0.949 LOCATION R 0.883 (ThaiNER v1.3 split เดียวกัน) | ~106M ~420MB fp32 / ~105MB int8 | ~1.3 s/ประโยค torch, ONNX int8 ~30-150 ms (ประมาณ) | CC-BY-SA 4.0 ต้อง review | ต้องมี NER head |
| thainer-v2 (แนะนำ primary) | F1 0.848 R 0.878 (Thai NER 2.0 model card) PER/LOC/ORG/AGE | ~100M | เท่า base | CC-BY-4.0 | มีในโค้ดแล้ว phone/email/ID ยังเป็นงาน FP regex |
| PhayaThaiBERT | ThaiNER micro 86.42 vs Wangchan 84.64 (paper split) | 278M ~1.1GB | ช้ากว่า base | ไม่ยืนยัน | +~2 micro เท่านั้น ได้ macro/loanword เป็นหลัก ไม่คุ้ม 2.6x |
| HoogBERTa | ไม่มีตัวเลข F1 เชื่อถือได้ (paper paywall) | ~106M | - | MIT | license ดีสุด แต่ recall พิสูจน์ไม่ได้ tokenizer subword-nmt ทำ Rust ยาก |
| XLM-R-base | micro-F1 0.833 R 0.858 (ThaiNER paper split) | ~270M ~1.1GB | ช้ากว่า Wangchan | MIT | ต่ำกว่าบนไทยล้วนที่ 2.6x size แต่ candle support ดีสุด |
| XLM-R-large | ไม่มีตัวเลข Thai NER | 550M ~2.2GB | หลายวินาที/ประโยค | MIT | หนักเกินสำหรับ laptop CPU ข้าม |
| mDeBERTa-v3-base | ไม่มีตัวเลข Thai NER (XNLI Thai 76.4 เท่านั้น) | 276M | - | MIT | disentangled attention ไม่มีใน candle พัง Rust path ข้าม |

คำแนะนำ ตั้ง thainer-v2 เป็น primary แล้วลด CRF เป็น first-pass tier เร็วที่คงไว้เกือบฟรี ตัดสินโมเดลด้วย PERSON/LOCATION recall ไม่ใช่ headline micro-F1 ราคาเดียวคือ latency ~1.3 s/ประโยคบน torch แก้ด้วย ONNX int8 ตัวเลข ThaiNER ทั้งหมดเป็นข่าวทางการ ข้อมูลจริง out-of-distribution ให้เผื่อ recall ต่ำกว่า lab

### แกน 2 Zero-shot NER / local LLM

| ตัวเลือก | metric + dataset | size | license | fit |
|---|---|---|---|---|
| GLiNER multi (urchade v2.1) แนะนำเสริม | ไม่มีตัวเลขไทย English OOD avg F1 47.8 (GLiNER benchmark 20 ชุด) | 289M ~2.31GB fp32 | Apache-2.0 | recall net ดีสุดในแกนนี้ ต้อง validate ไทยเอง |
| GLiNER-PII (nvidia/knowledgator/fastino) | F1 0.64 AI4Privacy / 0.87 Nemotron (nvidia) 80.99% synthetic (knowledgator) ทั้งหมดอังกฤษ | 205-570M | ผสม nvidia มี restriction | taxonomy PII พร้อม แต่ยังต้อง fine-tune ไทย |
| NuNER Zero | +3.1% เหนือ GLiNER-L English only | 0.4B | MIT | license สะอาดสุด path ไทยอ่อน |
| local small LLM (Qwen/Llama/Gemma GGUF) | proxy GPT-4o zero-shot PII R 0.437 wF1 0.558 (13-locale ไม่มีไทย) เล็กกว่าแย่กว่า | 1-3B | Qwen Apache-2.0 Llama/Gemma มี restriction | recall ต่ำ ช้าบน CPU JSON drift ไม่เหมาะเป็น detector หลัก |
| Thai LLM (Typhoon2 OpenThaiGPT) | ไม่มีตัวเลข PII ไทย (มีแต่ ThaiExam/M3Exam ทั่วไป) | 1-3B | Llama 3.2 Community restriction | เข้าใจไทยดี แต่ยังไม่พิสูจน์ PII |
| cloud LLM (GPT-4o/Claude) contrast | wF1 0.558 P 0.795 R 0.437 (13-locale ไม่มีไทย) | - | proprietary | ตัดออก ผิด privacy และ recall ยังไม่ผ่าน |

คำแนะนำ ใช้ GLiNER multi เป็น recall net union กับ regex+CRF โดยลด score threshold แต่ต้องปรับและวัดบนไทย fine-tune ยังเป็น detector หลักที่ถูกต้อง ไม่มีตัวเลือกในแกนนี้ที่มี recall PII ไทยตีพิมพ์เลย และ GLiNER/NuNER ไม่มี candle port ถ้าจะใส่ใน Rust binary ต้องมัด ort เป็นต้นทุนสถาปัตย์เพิ่ม

### แกน 3 OCR สแกนไทย ต้องได้ box

ตัวชี้ขาดคือ box ที่ align กับ pixel ไม่ใช่ text accuracy ล้วน VLM ที่ออก markdown ไม่มี box ตัดออกจาก path redaction

| engine | metric + dataset | box | size | license | Rust |
|---|---|---|---|---|---|
| PP-OCRv5 (th ปัจจุบัน) | 82.68% line exact-match (vendor Thai ~4,261 img ไม่ใช่ CER) >370 char/s Xeon | polygon จริง (line) | ~9.6MB CPU | Apache-2.0 | rust-paddle-ocr, oar-ocr |
| PaddleOCR-VL-0.9B | OmniDocBench 92.56 text edit 0.035 (ไม่มีตัวเลขไทย) | region/line predicted | 0.9B GPU | Apache-2.0 | candle native |
| EasyOCR | CER 0.086 PDF / 0.411 ลายมือ (openthaigpt 104 img) | quad จริง | หลายสิบ MB | Apache-2.0 | ต้อง ONNX ผ่าน ort |
| Tesseract (tha) | CER 0.762 PDF / 1.032 ลายมือ (แย่กว่าไม่ทำ) | word+line richest | เล็กมาก | Apache-2.0 | leptess |
| Typhoon OCR | Lev 0.07 BLEU 0.91 (vendor Thai) ดีสุดด้าน text | ไม่มี box | 2-8B GPU | Apache-2.0 | ไร้ประโยชน์ ไม่มี box |
| dots.ocr | edit dist 0.075 layout F1 0.93 (ไม่มีตัวเลขไทย) | grounding predicted | 1.7B GPU | MIT | ไม่มี |
| cloud Google/Azure | 96-99% field accuracy (ไม่ใช่ CER ไทย) | polygon | - | proprietary | ตัดออก ผิด privacy |

คำแนะนำ คง PP-OCRv5 เป็น primary เป็นตัวเดียวที่ครบทั้งโมเดลไทย box จริง footprint เล็ก และ Rust story มีจริง สำหรับ rewrite ให้ประเมิน PaddleOCR-VL ผ่าน candle เป็น accuracy ceiling ข้อจำกัด PP-OCRv5 ให้ box ระดับ line ไม่ใช่ per-word คือ redact PII หนึ่งคำจะทับทั้งบรรทัด รับได้ภายใต้ recall>precision และ box จาก VLM เป็น model-predicted อย่าใช้กับ blackout ถาวรก่อน validate

### แกน 4 PDF extract + true redaction

| lib | metric + dataset | box granularity | license | Rust |
|---|---|---|---|---|
| pypdfium2 (ปัจจุบัน) | 0.1s / 97% quality (py-pdf 14 doc ส่วนใหญ่อังกฤษ) สูงสุดในชุด | per-character | Apache-2.0 OR BSD-3 | engine เดียวกับ pdfium-render |
| pdfium-render (Rust target) | เท่า engine เดียวกัน | per-character | MIT OR Apache-2.0 | ตัวเลือก Rust ดีสุด engine-parity |
| pdfplumber (ปัจจุบัน) | 9.5s / 75% quality (ช้าสุด fidelity ต่ำสุด) | word bbox พร้อมใช้ | MIT | ไม่มี |
| PyMuPDF | 1250 pages/s 96% quality redaction ลบจริง (ดีสุดทางเทคนิค) | word | AGPL-3.0 ห้ามใช้ | - |
| borb | ไม่มีตัวเลข redaction ถูกต้อง | - | AGPL-3.0 ห้ามใช้ | - |
| lopdf / printpdf (Rust) | ไม่ใช่ extractor ใช้เขียน/rewrite PDF | - | MIT | complementary |

คำแนะนำ มาตรฐานเป็น PDFium ตัวเดียวทั้งสอง stack ทำให้ rewrite เป็น engine-parity port ไม่ต้อง re-validate ภาษาไทยบน engine ใหม่ คง flatten-to-image (rasterize + วาดกล่องดำ + rebuild ไม่มี text layer) อย่าถอยไปวาดสี่เหลี่ยมทับ text layer ที่ยังมีชีวิต นั่นไม่ใช่ redaction (เคส Manafort 2019 Epstein files กู้ข้อความคืนได้) ปัญหาสระ/วรรณยุกต์หายเกิดจาก ToUnicode CMap ของ PDF ต้นทาง เปลี่ยน extractor ไม่ช่วย ต้องพึ่ง OCR fallback และ PDFium binary เป็น single-maintainer ให้ vendor pinned build ใน repo

### แกน 5 Thai word segmentation

| tokenizer | metric + dataset | license | Rust |
|---|---|---|---|
| newmm (ปัจจุบัน) | BEST2010 acc 71.18% word-F1 74.77 ~0.85M chars/s | Apache-2.0 | เป้า parity |
| nlpo3 (แนะนำ) | ไทยล้วน 100% identical กับ newmm mixed digit/latin/punct ~93% overlap speedup 2.5-3.66x | Apache-2.0 | ตัวเดียว mature offline Rust |
| DeepCut | BEST word-F1 96.34 VISTEC 81.78 ช้ากว่า dict มาก | MIT | ผ่าน nlpo3 DeepcutTokenizer feature |
| AttaCut | BEST F1 91% เร็วกว่า DeepCut 6x | MIT | ไม่มี |
| OSKut/DSE | VISTEC word-F1 92.91 (SOTA social) ต้อง domain data หนัก | MIT | ไม่มี |
| ICU4X | ไม่มีตัวเลข BEST เชื่อถือได้ (ต่ำกว่า newmm เชิงคุณภาพ) | Unicode/ICU | pure Rust แต่คุณภาพไทยอ่อน |

คำแนะนำ คง nlpo3 boundary ไทยล้วน byte-identical กับ newmm จึงรักษา name/context span ไว้ครบ ข้อควรระวัง nlpo3 ไม่ใช่ byte-parity บนข้อความปน digit/latin/punct (อีเมล ID ที่อยู่มี slash) เหลือ overlap ~93% รับได้เพราะ structured PII จับด้วย regex บน raw text แต่ต้อง pin words_th.txt เวอร์ชันเดียวกันและเพิ่ม golden-corpus regression test tokenizer สำคัญน้อยกว่าที่คิดเพราะ WangchanBERTa ใช้ SentencePiece subword ของตัวเอง word tokenizer มีผลหลักกับ FP alignment และ context cue

### แกน 6 Rust inference backend + server

| ตัวเลือก | สถานะ + ตัวเลข | license | ความเสี่ยงสำหรับ core NER |
|---|---|---|---|
| ort (ONNX Runtime) แนะนำถ้าไป Rust | v2.0.0-rc int8 2.9x CPU speedup BERT-base (Microsoft) Roblox <1% F1 drop ~20ms adopters TEI/Magika/YOLO/SurrealDB | Apache-2.0/MIT (ORT MIT) | ต่ำ ขี่ runtime Microsoft แต่ link C++ lib ไม่ใช่ static เดี่ยว |
| candle (แผนปัจจุบัน) | 20.7k stars มี BERT แต่ไม่มี RoBERTa/token-class head ต้องพึ่ง crate 2-star 6-commit ไม่มี int8 encoder | Apache-2.0/MIT | สูง แขวน component สำคัญสุดบน crate งานอดิเรก |
| Python onnxruntime+optimum (คง FastAPI) แนะนำเสี่ยงต่ำสุด | onnxruntime wheel ~15-50MB vs torch 200MB-5GB int8 2.9x แก้ ~1.3s/ประโยคตรงจุด | MIT/Apache-2.0 | ต่ำสุด ไม่ rewrite ภาษา |
| tract (Sonos) | pure Rust แต่ transformer op ไม่ครบ (issue #331) ไม่มี int8 transformer | Apache-2.0/MIT | สูง ต้อง validate op เอง |
| Burn | ไม่มี turnkey RoBERTa NER ต้องพอร์ตเอง | Apache-2.0/MIT | สูงสุด over-scoped |
| axum (server) แนะนำ | ตาม actix ~10-15% throughput memory ต่ำสุด Tokio team maintain | MIT | bus-factor ดี |
| actix-web | เร็วสุด saturation แต่ actor overhead + วิกฤต maintainer ปี 2020 | MIT/Apache-2.0 | ไม่จำเป็นสำหรับ localhost |

คำแนะนำ ถ้าไป Rust ใช้ ort + int8 + axum ไม่ใช่ candle ไม่ใช่ actix ข้อควรระวัง int8 speedup ขึ้นกับ AVX2/AVX512-VNNI และ dynamic int8 อาจช้ากว่า fp32 ที่ seq ยาว >1024 token ต้อง benchmark เอง ไม่มี benchmark CPU RoBERTa token-classification candle vs ort แบบ apples-to-apples ที่หาได้

### แกน 7 Architecture + evaluation

| ตัวเลือก | metric + dataset | license | fit |
|---|---|---|---|
| Presidio (เป็น framework) | English clinical recall 0.74-0.81 cross-domain avg F1 0.481 (Sikkema) EMAIL F1 0.96-0.996 ไม่มีไทย | MIT | Python-only ชนแผน Rust จุดอ่อนคือชื่อ ตรงกับที่เราแก้อยู่แล้ว |
| ensemble เดิม (แนะนำคง) | hybrid regex+NER+context+validation = best practice (Nature 2025) มี leak-guard/validator ที่ Presidio ไม่มี | Apache-2.0 | on-target ปัญหาเดียวคือ recall ยังไม่วัด |
| presidio-evaluator (แนะนำ adopt) | span-level P/R/F2 (beta=2 เน้น recall) + template+fake-data generator | MIT | harness วัดผลที่ leverage สูงสุด |
| Piiranha-v1 (DeBERTa-v3 PII) | in-dist 98.27% acc F1 0.9312 cross-domain avg 0.542 (Sikkema) ไม่มีไทย | MIT | ใช้เป็น template ไม่ใช่ตัวไทย |
| GLiNER2-PII | 80.99% synthetic (knowledgator) SPY avg F1 0.471 (arXiv 2026 ยังไม่ verify) ไม่มีตัวเลขไทย | Apache-2.0 | recall net ที่ export ONNX ได้ ต้อง validate ไทย |
| AI4Privacy datasets | 200k/300k/500k = 6-8 ภาษายุโรป 2M = 32 locale ไทยไม่มีในทุก release ที่ยืนยันได้ | CC-BY-4.0 | ใช้เป็น label schema + English-minimum ไม่ใช่ Thai benchmark |

คำแนะนำ คง ensemble เดิมเป็น core แล้ว instrument ด้วย presidio-evaluator report span-level recall + F2 แยก FP (structured) กับ TB (free-text) และ gate การ rewrite ด้วย recall parity ก่อน/หลัง ตัวเลข vendor เป็น in-distribution ที่ overstate เสมอ (Piiranha 98.27% เป็น ~0.54 cross-domain) ให้เผื่อ recall จริงต่ำกว่า headline มาก

## 3 คำถามใหญ่ ควร rewrite เป็น Rust ไหม

ตอบตรงๆ อย่าเดิมพัน core NER ไว้กับ candle ตอนนี้ แผน Rust + candle + WangchanBERTa วางเดิมพันผิดจุด

เหตุผลจากงานวิจัย โมเดลที่จะรันคือ WangchanBERTa = RoBERTa-base (12 layer 768 hidden ~106M) แต่ candle ที่ 20.7k stars มี BERT ในรายการทางการ ไม่มี RoBERTa และไม่มี token-classification head และไม่มี int8 quant สำหรับ encoder ทางเดียวคือแขวนไว้กับ crate nicksenger/candle-token-classification ที่มี 2 stars 6 commits ผู้เขียนเองบอกว่า likely missing things หรือเขียนโมเดลเอง นี่คือ bus-factor ที่แย่ที่สุดสำหรับ solo dev บน component ที่ recall เป็นตาย

recommendation แบบ risk-adjusted เรียงจากเสี่ยงต่ำไปสูง

1. เสี่ยงต่ำสุด อยู่ Python ต่อ FastAPI + onnxruntime + optimum + WangchanBERTa int8 ได้ speedup 2.9x (Microsoft BERT-base) แก้ ~1.3s/ประโยคตรงจุด และตัวการ bloat จริงคือ torch (200MB-5GB) ไม่ใช่ Python เอง สลับ torch เป็น onnxruntime (~15-50MB) คือสิ่งที่ฆ่า PyInstaller bloat ที่ rewrite ตั้งใจแก้ตั้งแต่แรก ได้ประโยชน์ 80% ที่ความเสี่ยงเศษเดียว
2. ถ้ายืนยันจะไป Rust ใช้ ort (ONNX Runtime) ไม่ใช่ candle export WangchanBERTa เป็น ONNX ผ่าน optimum ทำ int8 dynamic quant (Roblox <1% F1 drop ~20ms median CPU) serve หลัง axum ort ขี่ runtime ของ Microsoft ที่ battle-tested เสี่ยงเฉพาะ binding บางๆ ไม่ใช่ตัว runtime
3. เสี่ยงสูง candle สำหรับ core NER วันนี้ อย่าเพิ่ง

ข้อแม้สำคัญ ort ไม่ใช่ static binary เดี่ยว เพราะ link onnxruntime.dll ถ้า single self-contained binary เป็น requirement แข็ง มีแต่ candle/tract/Burn ที่ผ่าน แต่ทั้งหมดมีช่องว่างโมเดลตามที่ว่า สำหรับ recall-critical component น้ำหนักเอียงไป ort ชัดเจน

จุดที่เห็นต่างจากแผนปัจจุบัน แผนล็อค candle ไว้ เอกสารนี้ไม่เห็นด้วยสำหรับ NER path ให้ทำ Rust rewrite เฉพาะ shell (axum, pdfium-render, nlpo3, FP regex, orchestration) ที่ Rust ชนะชัด แต่ gate NER-in-Rust ด้วยการวัด recall parity บน benchmark ไทยก่อน และให้ NER เป็น bundled ONNX ผ่าน ort ไม่ใช่โค้ด candle เขียนใหม่

## 4 จุดที่ cloud ชนะ local

ยอมรับตามจริง cloud ชนะ local สองจุด

- OCR สแกนไทยยากๆ Google Document AI / Azure Document Intelligence (Azure รองรับ locale th คืน polygon per line/word) เหนือ local ชัดบนสแกนลายมือหรือคุณภาพต่ำ ที่ PP-OCRv5/EasyOCR พลาด (EasyOCR CER ลายมือ 0.411 Tesseract 1.032)
- LLM extraction cloud frontier มี ceiling สูงกว่า local small LLM แต่ระวัง แม้แต่ GPT-4o zero-shot ก็ได้ recall แค่ 0.437 ยังไม่ผ่าน bar recall-first อยู่ดีถ้าไม่ fine-tune

แต่ทั้งสองอย่างส่ง pixel/ข้อความดิบออกนอกเครื่อง = ทำลาย privacy invariant ที่เป็นเหตุผลทั้งหมดของ product ควรเป็น opt-in ต่อเอกสารเท่านั้น แยก path ให้ชัดจาก private path และไม่มีวันเป็น default

## 5 ความเสี่ยงและช่องว่างของข้อมูล และสิ่งที่ต้องทำก่อน

สิ่งที่ตัวเลขไม่ได้บอกเรา

- F1 Thai NER ทั่วไป ไม่ใช่ PII recall ให้ตัดสินด้วย per-class recall ของ PERSON/LOCATION ไม่ใช่ headline micro-F1
- ไม่มี benchmark PII ภาษาไทยสาธารณะเลย ไม่มีอะไร off-the-shelf มาวัด recall PII ของเราได้
- ตัวเลข lab เป็น formal news ข้อมูลจริง out-of-distribution ให้เผื่อต่ำกว่า
- ตัวเลข vendor เป็น in-distribution overstate จริง วัดบนไทยเอง
- ตัวเลข latency int8 และ tokens/sec local LLM เป็นค่าประมาณจากฮาร์ดแวร์อื่น ไม่ใช่ไทยที่วัดจริง
- benchmark ปี 2026 หลายชิ้น (SPY/GLiNER2-PII, PIIBench) เป็น arXiv preprint ยังไม่ verify เต็ม ให้ถือเป็น secondary

สิ่งเดียวที่ต้องสร้างก่อนเพื่อ de-risk ทุกอย่าง benchmark recall PII ภาษาไทย

- สร้าง synthetic ด้วยวิธี template + fake-data ของ presidio-evaluator reuse generator ไทยที่มีอยู่ (fp_generator/tb_generator)
- บวก gold set เอกสารจริง label มือ ~100-300 เอกสาร เพื่อ external validity เพราะ synthetic อย่างเดียว over-state recall
- report span-level recall + F2 (beta=2) แยก FP (structured) กับ TB (free-text) ต่อชนิด entity
- ใช้ benchmark นี้ gate การ rewrite ต้องพิสูจน์ recall parity ก่อน/หลัง export ONNX ก่อนจะ commit อะไรลง Rust

ถ้าทำสิ่งนี้ก่อนสิ่งเดียว การตัดสินใจทุกแกน (CRF vs WangchanBERTa, candle vs ort, Python vs Rust) จะมีตัวเลขจริงมา gate แทนการเดา ซึ่งตอนนี้ทั้งหมดยังตัดสินบน proxy

## 6 แหล่งอ้างอิงหลัก

Thai NER encoder
- WangchanBERTa + ThaiNER benchmark https://arxiv.org/abs/2101.09635
- thainer-v2 model card https://huggingface.co/pythainlp/thainer-corpus-v2-base-model
- PhayaThaiBERT https://arxiv.org/abs/2311.12475
- HoogBERTa https://github.com/lstnlp/HoogBERTa , https://ieeexplore.ieee.org/document/9678190
- XLM-R / mDeBERTa https://huggingface.co/FacebookAI/xlm-roberta-large , https://huggingface.co/microsoft/mdeberta-v3-base

Zero-shot / LLM
- GLiNER multi https://huggingface.co/urchade/gliner_multi-v2.1
- GLiNER-PII https://build.nvidia.com/nvidia/gliner-pii/modelcard , https://huggingface.co/knowledgator/gliner-pii-base-v1.0
- NuNER Zero https://huggingface.co/numind/NuNER_Zero
- Typhoon 2 https://medium.com/scb10x/introducing-typhoon-2-0806fb040c45

OCR
- PP-OCRv5 Thai https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.en.md , https://huggingface.co/blog/baidu/ppocrv5
- PaddleOCR-VL https://huggingface.co/PaddlePaddle/PaddleOCR-VL , https://docs.rs/candle-transformers/latest/candle_transformers/models/paddleocr_vl/index.html
- rust-paddle-ocr https://github.com/zibo-chen/rust-paddle-ocr , oar-ocr https://crates.io/crates/oar-ocr
- EasyOCR Thai eval (openthaigpt) , Typhoon OCR https://huggingface.co/scb10x/typhoon-ocr-7b
- Azure th OCR https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/language-support/ocr?view=doc-intel-4.0.0

PDF
- py-pdf benchmarks https://github.com/py-pdf/benchmarks
- pdfium-render https://github.com/ajrcarey/pdfium-render , pinned binaries https://github.com/bblanchon/pdfium-binaries
- pypdfium2 https://github.com/pypdfium2-team/pypdfium2 , pdfplumber https://github.com/jsvine/pdfplumber

Tokenizer
- nlpo3 vs newmm benchmark https://dev.to/veer66/thai-word-tokenizers-benchmark-nlpo3-vs-newmm-314n , https://github.com/PyThaiNLP/nlpo3
- OSKut https://github.com/mrpeerat/OSKut , DeepCut https://github.com/rkcosmos/deepcut

Rust inference / server
- ort https://github.com/pykeio/ort
- candle https://github.com/huggingface/candle , token-class crate https://github.com/nicksenger/candle-token-classification
- ONNX int8 speedup https://medium.com/microsoftazure/faster-and-smaller-quantized-nlp-with-hugging-face-and-onnx-runtime-ec5525473bb7 , https://blog.x.com/engineering/en_us/topics/insights/2021/speeding-up-transformer-cpu-inference-in-google-cloud
- tract issue https://github.com/sonos/tract/issues/331

Architecture / eval
- Presidio https://microsoft.github.io/presidio/ , presidio-research https://github.com/microsoft/presidio-research
- open-source PII benchmark (Sikkema) https://albertsikkema.com/python/security/privacy/2026/06/01/benchmarking-open-source-pii-detection.html
- Piiranha https://huggingface.co/iiiorg/piiranha-v1-detect-personal-information
- AI4Privacy https://huggingface.co/ai4privacy
