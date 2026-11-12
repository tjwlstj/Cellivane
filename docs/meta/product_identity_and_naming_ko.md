# Cellivane · 셀리베인 제품 이름과 역할 경계

> 문서 역할: 제품 표시 이름·호환 이름·구성요소 명칭 정본
>
> 문서 수명주기: 활성
>
> 채택·내용 검토일: 2026-10-09 — 사용자 요청에 따라 Cellivane을 제품 이름으로 채택하고 기존 AIOS 기술 계약과 구분
>
> 외부 이름 조사일: 2026-10-09; 제한된 공개 검색이며 상표 권리·도메인 확보 판정이 아님
>
> 상위 연결: [제품 목적](aios_product_direction_ko.md), [전역 큐](minimal_io_and_maturity_workflow_ko.md#serve-p1a-current), [문서 신선도 원장](document_freshness_registry_ko.md)

## 1. 채택한 이름과 우리가 부여한 뜻

제품 표시 이름은 **Cellivane**, 한국어 표기는 **셀리베인**으로 통일한다.
한국어 음절은 `셀·리·베·인`의 네 음절이다. 기존 **AIOS**는 저장소와 실행 계약을
읽을 때 필요한 기술·호환 이름으로 유지한다.

Cellivane은 **Cell과 vane의 이미지를 결합해 우리가 만든 조어**다. Cell은 관리 범위와
AI가 활동하는 공간을, vane은 상태와 방향을 읽어 다음 움직임을 돕는 이미지를 담는다.
이는 제품에 **우리가 부여한 뜻**이며 사전에 등재된 어원이나 외부에서 확인된 의미라는
주장이 아니다. 이름은 특정 모델이나 엔진 하나를 넘어 관리 구조·로컬 실행·사용자와의
활동을 포괄한다.

제품 목적은 AI가 작업 공간과 현재 상태를 이해하고, 로컬 자원에서 효율적이고 안정적으로
활동하며, 사용자와 지속적으로 상호작용하는 운영 환경이다. 이름 채택은 그 목적의 변경이나
native 커널·심핵·고권한 집행·설치 완료 판정이 아니다.

## 2. 영문·한글 표기와 책임

| 대상 | 영문 표시 | 한글 표시 | 맡는 의미와 경계 |
|---|---|---|---|
| 전체 제품 | Cellivane | 셀리베인 | 사용자와 AI의 생활·작업 운영 환경. hosted delivery와 독자 native 목표를 함께 설명 |
| 기술·호환 이름 | AIOS | AIOS | 기존 repository/module/CLI/schema/ABI/artifact identity. 새 표시 이름과 함께 유지 |
| 동반자 | Chesi | 체시 | 사용자와 함께 작업하는 동반자·운용 persona. 이름이 principal·권한·canonical Node identity가 되지 않음 |
| 관리 아키텍처 | Kernel Room | 커널룸 | Room → Cell → Node → NodeBit의 식별·관계·상태·세대·유효성 관리. 제품 전체나 화면의 방과 구분 |
| 제품 실행층 | Cellivane Runtime | 셀리베인 런타임 | hosted 요청 접수·Task 수명·source/관리 계약의 소비. Linux-hosted delivery와 native proof를 구분 |
| 사용자 입구 | Cellivane Console | 셀리베인 콘솔 | 상태·요청·결과·개입을 보여 주는 입구. 현재 `aios>` prompt와 CLI 제품 field는 유지 |
| 모델 실행기 | Engine | 엔진 | 외부 모델 backend와 프로토콜 어댑터의 역할. 제품명·동반자·model identity와 구분 |
| 독자 커널 경로 | Cellivane Native Kernel | 셀리베인 네이티브 커널 | 독자 x86_64 reference/proof 경로의 설명 이름. 현재 AIOS ABI·marker·파일명 유지 |

일반 제품 소개에는 `Cellivane · 셀리베인`을 쓰고, 호환 맥락이 필요한 첫 소개에는
`Cellivane (AIOS 기술·호환 이름 유지)`를 쓴다. Runtime/Console/Native Kernel은 위
역할의 표시 이름이며 해당 이름의 새 package·명령·binary가 생겼다는 뜻이 아니다.

Engine은 [서빙 계약](../os/aios_serving_design_ko.md)을 따른다. 어댑터 종류와 wire protocol,
배포의 model/service/instance identity·start generation, capability evidence를 구분한다.
`llamafile`, `llama.cpp`, `Ollama` 같은 upstream 실행기 이름을 Cellivane 자체 엔진의
고유 이름으로 바꾸지 않는다. Kernel Room의 명칭·관리 의미는 [관리 정본](../kernel-room/kernel_room_management_model_ko.md)이 소유한다.

## 3. 공개 이름 조사와 선택 근거

2026-10-09 공개 웹에서 quoted exact name과 software/AI/OS/kernel, GitHub·PyPI·npm
도메인, 한글 표기를 조합해 후보를 검토했다. 아래 공식 프로젝트·제품 페이지는 가까운
영역에서 같은 표기를 이미 사용하는 사례다. 검색 결과와 제품의 설치·호환·실행 검증은
별개이며 이 조사에서는 외부 제품을 설치하거나 코드를 반입하지 않았다.

| 이름 | 확인한 공개 사용과 공식 근거 | 이번 판단 |
|---|---|---|
| AIOS | [agiresearch/AIOS](https://github.com/agiresearch/AIOS)는 agent OS와 기존 OS 위의 kernel abstraction을 설명 | 우리 독자 제품의 표시 이름을 구분할 이유. 외부 프로젝트명은 원문 유지 |
| Orivane | [공식 repository](https://github.com/wieslawsoltes/Orivane)의 협업 whiteboard | 가까운 software 분야의 동일 표기를 피해 제외 |
| Nuvora | [공식 workspace 도움말](https://www.nuvora.studio/help), [공식 AI 제품](https://nuvoralabs.net/products) | AI/workspace 분야의 동일 표기로 제외 |
| Cellora | [공식 repository](https://github.com/Antismart/cellora)의 Rust CKB indexer | software 분야의 동일 표기로 제외 |
| Aivora | [공식 conversational AI](https://aivora.ai/en/), [공식 agent 제품](https://aivorai.com/product.html) | AI 분야의 동일 표기로 제외 |
| Velora | [공식 desktop 다운로드](https://www.runvelora.app/download)의 모델·coding agent workspace | 제품 사용 맥락이 가까워 제외 |
| Orivela | [공식 상점](https://orivela.pl/), [일본 상점](https://shop.orivela.jp/) | 동일 표기의 상업 사용을 확인해 제외 |

추가 후보 Cellivane·Nodivane의 조사에서는 경쟁 OS/AI/software 프로젝트를 확인하지
못했다. Cellivane에는 제품과 무관한 개인 reviewer·자동 transcript hit가 있었고,
Nodivane에는 오래된 OCR hit가 있었다. 다른 후보는 [Rovelith 판매자](https://shop.tiktok.com/us/pdp/1732539205989864445),
[Aevorin 제작자 상점](https://www.etsy.com/shop/Aevorin), [Ruvyra 사이트](https://ruvyra.com/about) 등
동일 표기 사용을 확인했다. 최종 Cellivane 선택은 이런 제한된 검색 결과와 네 음절 표기,
공간·관리·방향을 함께 표현하려는 자체 naming intent에 근거한다.

**미검출은 배타적 사용 가능성의 증명이 아니다.** 상표 등록·권리 충돌, 모든 국가·언어의
사용, 도메인·패키지 이름의 확보나 향후 가용성은 확인하지 않았다. 공개 검색 색인과
움직이는 공식 페이지에는 누락·변경 가능성이 있다. 이름을 실제 배포·등록하는 시점에
그 범위를 다시 검토한다.

이 자료는 이름 선정 참고다. upstream source 정책의 13개 row나 `code_import=0` 경계를
바꾸지 않으며, 상표·라이선스·code import 승인 또는 외부 runtime qualification을 만들지 않는다.

## 4. 이번 표시 개정과 호환 유지

이번에는 제품 headline·첫 소개·정본 링크와 역할 표를 바꾼다. 다음 기술 값은 기존
계약을 유지한다.

- `aios_*` module/package, `aios-*` repository skill, CLI prompt·제품 field·명령과 launcher 이름
- public numeric ID, native ABI, schema/version, protocol family, receipt, boot marker
- 기존 경로·파일명, source manifest의 실제 path, 과거 image·log·artifact·hash·verdict
- `agiresearch/AIOS` 등 외부 고유 이름과 인용한 입력 파일의 원래 제목

이 항목을 migration할 때는 표시 개정과 별도 조각으로 선택하고 producer·consumer·
검증기·배포·복구·이전 artifact의 호환 조건을 함께 정한다. 이름 문자열의 일괄 치환으로
기술 계약이나 보존된 역사 증거를 다시 쓰지 않는다.

## 5. 현재 개발과 성숙도의 연결

현재 선택한 고도화는 [SERVE-P1a](../os/aios_serving_design_ko.md#serve-p1a-current)다.
내부 explicit messages selector, closed prepared와 bounded HTTP worker, 공통 Task
lifetime을 붙여 localhost HTTP fixture와 독립 증거 검증을 수행하는 작은 hosted 조각이다.
개발은 `PARTIAL`이며 좁은 회귀·4종 Task의 HTTP fixture 독립 판독은 PASS다.
전체 판정·전용 source33와 public family32의 근거는 서빙 정본이 소유하며 이름 문서에서 중복하지 않는다.

P0·구조 최적화의 `PARTIAL`과 원본 source별 PASS/FAIL은 보존한다. native K1/K2-a의
bounded `CURRENT`, 전체 관리 topology `PARTIAL`, Linux-hosted 기본 delivery와 native
proof의 분리도 유지한다. 실제 Ollama·managed llama.cpp, 공개 CLI 엔진 선택, parallel·
stream·shared memory bridge, 새 native 경로·고권한·심핵·portable 설치 완료는 후속이다.
제품 이름의 채택으로 이들의 `PLANNED`/`NOT_RUN` 경계를 승격하지 않는다.

## 6. 문서 소유와 재검토

이 문서는 이름과 역할 경계를 소유한다. 제품 성공 기준은 제품 목적 정본, 전역 우선순위는
전역 큐, 관리 의미는 Kernel Room 정본, 실행·검증 결과는 각 운영/서빙 가이드가 소유한다.
README·PROJECT·CLAUDE·hosted/문서 색인은 짧게 요약하고 이 문서에 연결한다.

재검토 조건은 이름·표기·역할 변경, 공개 배포/등록, CLI·package·ABI migration,
충돌 정보 발견, 외부 근거의 재사용 또는 조사 후 30일이다. [신선도 원장](document_freshness_registry_ko.md)에
내용 검토일·외부 조사일·실행 증거의 날짜를 따로 기록한다.
