<!-- Cellivane public migration, 2026-11-12 -->
> 기존 구현·실행 기록은 가져온 source 시점의 범위다. 새 공개판 목적·전역 큐·개발·출처는 root README와 docs/PRODUCT.md, docs/ROADMAP.md, docs/DEVELOPMENT.md, docs/provenance/MIGRATION.md를 따른다. 이 안내는 새 runtime 수락을 뜻하지 않는다.

# Cellivane · 셀리베인 문서 신선도 원장

> 문서 역할: 사람용 내용 검토·재검토 조건 원장
> 문서 수명주기: 활성
> 마지막 내용 검토: 2026-10-12 — Seed 실제 CPU/cache·기존 bridge 호환 PASS와 최종 회귀 경계 연결; 과거 source별 증거 보존
> 이번 검토 경계: 아래 추가 검토 설명과 해당 행의 범위만 갱신했다. 2026-09-09의 문서 역할 정비·당시 v0.8 소스 대조와 외부 기준일은 보존하며 실제 모델 Task·새 이미지 실행 판정과 구분한다.

이 원장은 **어떤 사실을 어느 문서에서 확인하고, 언제 다시 확인할지**를 관리한다.
[문서 색인](../README.md)은 탐색, [통합 작업 진입 가이드](integrated_work_guide_ko.md)는
요청별 작업 절차를 소유한다. 제품 목적은 [제품 방향 정본](aios_product_direction_ko.md),
현재 전역 작업 큐는 [성숙도 작업흐름](minimal_io_and_maturity_workflow_ko.md)이 소유한다.
이 표의 재검토 후속은 문서 확인 조건이며 새 구현 우선순위가 아니다.

2026-10-12 추가 내용 검토: [Seed 정본](../os/cellivane_seed_engine_ko.md)에 자체 scheduler·완료 cache·동일 flight 합류와 외부 CPU worker의 책임을 기록했다.
현재 큐는 Seed이며 실제 CPU/cache·기존 bridge 호환은 한정 PASS, 품질 개선 없음·최종 회귀는 정본에 위임한다. 기존 브릿지·P1a·public family·이미지·native 성숙도와 원본 증거는 보존한다.

2026-10-09 추가 내용 검토: [브릿지 실험](../os/cellivane_bridge_experiment_ko.md)의
독립 runtime/tools 책임, 실제 소형 모델·D:·Job 기록, 품질 오답과 Strata UNKNOWN 차단을
대조했다. 전역 큐의 현재 선택을 이 격리 실험으로 연결하고 기존 P1a·Linux public source
family·native/이미지 성숙도를 유지한다. 상세 실행·최초 실패·독립 판독은 실험 정본이 소유한다.

2026-10-09 내용 검토: [제품 이름 정본](product_identity_and_naming_ko.md)에 Cellivane·
셀리베인, AIOS 기술·호환 이름과 Chesi·Kernel Room·Runtime·Console·Engine 역할을 기록했다.
온라인 근거의 실제 조사일은 2026-10-09이며 제한된 미검출·상표/도메인 미확정 경계를 유지한다.
표시 개정은 native/CLI/wire/ABI·upstream 이름·보존된 artifact의 migration이 아니다.
[SERVE-P1a](../os/aios_serving_design_ko.md#serve-p1a-current)는 내부 Ollama chat 입구·HTTP
fixture의 개발 조각이다. public source32/CLI39/backend19와 optional 전용 closure33·전체
Python/candidate44를 구분한다. 최초31·영향77·독립 verifier28·candidate7 검사는 PASS이고
4종 HTTP Task의 source33 독립 CLI도 각 exit0/PASS다. Windows 전체 회귀 PASS와 플랫폼/
권한 skip·최초 환경 실패·최종 판정·source/hash는 서빙§9가 소유하며 실제 서버·이미지·parallel·
shared memory·native qualification은 이번 문서 대조로 승격하지 않는다. 엔진 조율
설계는 bounded PLANNED 후속의 진입 링크만 연결하며 원본 P0/구조·round08/QEMU 실패는 보존한다.

2026-10-08 후속 내용 검토: 공식 upstream 자료의 서빙·에이전트·권한·native 설계를
[비교·채택 기록](../os/aios_architecture_comparison_20261008_ko.md)에 모았다. 움직이는
latest/main/master와 immutable pin 미확보, 직접 확인한 라이선스의 범위·개별 파일
review 미실행, code_import0/resource13 유지 경계를 기록한다. 내부 prepared 검증·
admission/lifetime 책임 분리를 새 source의 후속 조각으로 선택했다. shadow mock 원본과
수정 후 narrow66·최종 전체 회귀·새 source32 독립 fixture 판독의 PASS를 구분한다.
정확한 수치·최종 source/hash·원본과 후속 로그는 비교 기록 §6이 소유한다.
기존 P0 원본 및 아래 역사 실행·round08 P2를 수정하거나 새 source의 proof로 승계하지 않는다.
성능 benchmark·실제 서버·이미지·native 실행은 이번 조사·문서 변경의 범위 밖이다.

2026-10-08 SERVE-P0 내용 검토: 서빙 설계·인계의 SHA와 현재 beta 기준 소스를 대조하고
사용자가 선택한 SERVE-P0를 전역 큐에 연결했다. 최소 어댑터/capability·legacy receipt 3·
normalized fixture envelope·actual Task 수명과 CLI session11/MAIN run7/backend run2/source43 inventory의
경계를 기록한다. 이번 회귀 실행 결과는 [서빙 정본](../os/aios_serving_design_ko.md#6-검증-기록)이
소유한다. legacy107/실행104 PASS·Linux3 skip, messages17·H1 trust 수정37
PASS와 수정 뒤 전체 hosted1055(실행970 PASS·skip85·332.954초)를 기록한다. 초기·최종 source32
fixture bundle의 먼저 저장한 verdict는 각각 독립 PASS이며 실제 엔진·process liveness 판정이 아니다.
전체 실행 뒤의 독립 verifier 응답 상한 불일치는 runtime의 16384 bytes와 일치시켜
수정했고, 최종11개 검사와 현재 CLI source32 bundle의 별도 판독도 PASS다.
최종 verifier 수정과 앞선 전체1055 실행의 source/검사 범위를 구별한다.
첫 전체 FAIL4/ERROR18/skip85 원본과 수정 경위를 보존한다. 로컬 ego 방향 worktree의 미커밋 22개는 흡수하지 않고
제품·설치 목표만 출처와 `PLANNED` 경계로 보존했다. round08 P2·연구 원본 FAIL과
QEMU 두 시도 FAIL은 재검토·수정한 결과가 아니다. 실제 엔진·이미지·native/실기기 실행은
이번 문서 대조에 포함하지 않는다.
CLI11 EvidenceReport producer와 역사 schema10 validator의 runtime 결합도 아직
미지원이며 실제 QEMU 재실행은 없다. TaskSmoke session10/11 reader와 current source
검사 연결을 이 미완료 통합이나 source43 운영 이미지 acceptance로 승격하지 않는다.

2026-09-13 추가 내용 검토: 이 체크포인트의 개발 소스 v0.10의 문맥·접수·조회·결과·취소 계약과
보존된 결과, 새 Windows hosted 전체 990개 수집·85개 제외 및 Linux Task fixture 3개
PASS를 대조했다. 검사 대상 runtime·계약·도구 소스는 150개이며 Python 파일만의 수가 아니다.
실제 모델 `task-model-smoke-01`은 정상 답변·진행 중 Task 취소·worker/전체 backend 종료와
정상 VM 종료의 한정 범위에서 PASS다. 보존 source의 독립 재생도 PASS이며 원본 artifact 222개와
runtime 39개·검사 대상 source 150개의 불변·일치 범위를 확인했다. 새 이미지 acceptance와
외부 자료 재검토는 수행하지 않았다. 아래 해당 행만 갱신하며 과거 source와 외부 기준일은 유지한다.

같은 날 추가한 자기 참조 실증 검토는 사용자가 승인한 반복 절차와 전체 다섯 단계 수락
기준, 첫 Windows CPU sandbox pilot의 6개 scenario·4필드 출력·독립 검증·CI 구성의
소스 대조다. 이어 첫 pilot의 명시적 중단·FAIL/NOT_EVALUABLE, 원본 409개 불변과
규칙 실행 79개/6 episode/27 decision 독립 재생, derived attribution 입력 제거와
normal 3 episode calibration 선행을 대조했다. 별도 2호출 prompt probe의 행동/귀속
분리도 확인했다. calibration-01 원본은 3/3 episode·24모델응답·무결성 PASS지만 모델
목표 완료 0이다. 보존된 v2 이전 scorer의 calibration 249파일/3episode/28decision/24query와
rules-02 79파일/6episode/27decision 재생은 PASS, 원본 328개는 불변이다.
GPT의 공개 피드백 예측 credit 지적과 실제 파일 14 World 재현의 영향 범위를
대조했다. 이어 validation-02의 134개/132 PASS·2 skip·104.096초, source별 검사 범위와
grammar probe의 6응답/파일 행동 0·ON 형식/귀속 오류를 확인했다. 당시 validation-03은
135개/133 PASS·2 skip·106.369초이며 grammar probe 독립 감사 78파일 PASS도 대조했다.
calibration-02 ON 재생은 250파일/3episode/28decision/24query PASS지만 모델 목표는
양쪽 모두 0이다. OFF는 22HTTP 응답 중 마지막 생성 미완료로 FAIL/NOT_EVALUABLE,
관계 episode 미완료다. 원본 479개 불변·조건 대조 PASS와 별개로 전체 ON/OFF 비교는
NOT_EVALUABLE이며 효과 비교를 수행하지 않았다. 마지막 실패 응답 포함 비용과 게시 전
grammar 끝 LF 정리의 byte 경계, 새 코드의 rules-04 독립 재생 PASS를 정본 §6과 대조했다.
이후 ae20 원격 Windows 실패와 경로 수정, b60 CI 7/7 PASS·artifact 감사는 연구 가이드
§6.4–§6.5에 구분했다. 새 schema v2의 두 prompt 비교와 당시 Windows 191개 중
188 PASS·권한 조건 3 skip·178.638초, 실제 두 episode·24 HTTP 200·독립 감사 PASS를
대조했다. 원본 289파일·호출자 19파일·현재 source 14개·trusted consumer 3개는 불변이며,
두 조건 모두 OBSERVE/SELF 반복·목표 0으로 후보 개선을 관측하지 못했다.
그 단계의 개발 구현은 `PARTIAL`이며 후속 원문 진단·기존 GPT의 다음 실험안 검토와
새 v2 source의 CI는 당시 별도 확인 대상이었다. 외부 연구의 현재 사실을 확인한
것으로 기록하지 않는다.

2026-09-24 추가 내용 검토: bfea의 두 CI 7/7 terminal success와 서로 다른 artifact
감사 범위, GPT round06의 제공 자료만을 대상으로 한 검토·한 변경 채택을 연구 가이드
§7.4와 대조했다. 고정 상태의 관측 블록 순서만 바꾼 readout은 새 6 HTTP 200·
실행 무결성 PASS, 새 묶음 379파일의 독립 감사 PASS다. 원본 289파일·호출자 26파일·
연구 source/test 19개·trusted source 6개·driver 불변과 raw 비용을 확인했다.
두 조건 모두 OBSERVE/SELF 세 번으로 action/revision 1/3·귀속 0/3이며 개선은 미관측이다.
현재 Windows 전체 검사는 238개 중 234 PASS·link 권한 조건 4 skip·978.276초이고
실제 8.3 TEMP 별칭·source 19개 불변·기존 14개의 과거 실제 실행과의 일치를 확인했다.
개발 구현은 `PARTIAL`, 결과는 `STATIC_ONLY`로 실제 행동·목표 완료를 시험하지 않았다.
이후 readout 게시 SHA `5bd35e81`의 CI 7/7과 별도 artifact 감사, 기존 GPT 대화의
제공 자료 한정 검토를 대조했다. `evidence-report-feedback-v1`은 E0 계획 생성·
별도 두 UUID Task driver·독립 계약 코드가 준비된 `PREPARED`다. 실제 QEMU run01은
토큰 예산 초과로 Task 0개, run02는 첫 Task 접수 후 답변 미완료로 독립 FAIL이다.
저장·E1 피드백은 실행되지 않았고 합성 검사는 이를 대신하지 않는다. 장기 다섯 단계는 미완료다.
이번 내용 검토는 새 운영 이미지·native 권한·가중치 학습 검증을 포함하지 않는다.

## 1. 읽는 방법

- **역할·수명주기**는 각 문서의 상단과 색인을 대조한 값이다. 수명주기 `활성`은
  현재 계약이나 절차로 사용하는 문서, `REVIEW`는 현재 정본과 대조할 참고,
  `OLD`는 역사 기록을 뜻한다. 구현의 `CURRENT/PARTIAL/PLANNED`와 별개다.
- **마지막 내용 검토일**에는 검토한 범위를 함께 적는다. 기존 문서가 갱신일만
  기록했다면 그 사실을 표시한다. 날짜가 없으면 `미기록`으로 남긴다.
- **근거 기준·범위**는 별도의 시점이다. 오늘 목적·링크·문구를 정리해도 과거 실행의
  source pin, 검증일, 외부 자료 확인일은 그대로다. 표 전체가 최근 갱신됐다는 이유로
  모든 행의 기술적 근거가 최신이라고 읽지 않는다.
- **담당·후속**은 문서의 사실 소유 도메인과 다음 확인 책임을 뜻한다. 특정 AI 세션을
  영구 소유자로 두지 않는다. 세션이 바뀌어도 문서·코드·보존 증거에서 확인한다.

2026-09-09에는 아래 문서의 역할과 연결을 대조하고, 후속 v0.8 개발 변경이 영향을 주는
문서는 해당 코드·검증 경로를 추가 대조했다. 모든 본문을 현재 runtime으로
재검증하거나 모든 외부 링크의 현재 내용을 다시 조사한 것은 아니다. 이 범위 밖의
문서는 [전체 색인](../README.md)에서 찾고, 작업에 사용하게 될 때 필요한 행을 추가한다.

## 2. 재검토 규칙

| 조건 | 필요한 확인 | 완료 기록 |
|---|---|---|
| 제품 목적·관리 의미·전역 우선순위 변경 | 해당 정본을 먼저 고치고 영향을 받는 계약·색인·mirror를 대조 | 내용 검토일과 바뀐 범위; 실행 성숙도는 별도 근거가 있을 때만 수정 |
| API·schema·명령·경로·source 목록·권한·실행 방법 변경 | 그 사실의 소유 가이드와 실제 코드·검증 경로 대조 | 바뀐 계약과 유효한 증거의 source 범위; 과거 기록은 보존 |
| 관련 작업 착수 | 결정에 필요한 현재 branch·파일·도구·권한·관측 시점을 확인 | 확인한 상태와 미확인 사항을 해당 작업 결과에 남김; 전체 문서를 다시 읽을 필요 없음 |
| 외부 근거 확인 후 30일 경과, 관련 작업 착수, 또는 release/API/EOL 변경 인지 | 사용할 주장에 한해 공식 1차 자료를 다시 확인 | 실제 확인일·정확한 URL/버전·달라진 주장. 자동 pin 변경이나 upstream 코드 반입은 하지 않음 |
| `REVIEW/OLD` 문서를 현재 설계에 인용 | 현재 정본·코드와 충돌하는 전제부터 구분 | 유효한 참고 범위만 인용; 문서 안의 “다음”을 전역 큐로 복사하지 않음 |
| 링크·서식만 수정 | 경로와 문서 역할의 일치 확인 | 링크 정비 범위만 기록; 기술 내용·외부 자료·실행 검토일을 새 날짜로 덮지 않음 |

30일은 외부 정보를 의사결정에 다시 쓰기 위한 **재확인 기준**이다. 모든 문서를 매달
일괄 수정하라는 뜻은 아니며, 안정된 내부 계약을 문서 나이만으로 무효화하지 않는다.
공식 자료를 확인할 수 없으면 해당 주장과 확인 필요 조건을 남기고, 이를 새 기술 선택의
확정 근거로 사용하지 않는다. 관련 없는 작업까지 멈추거나 구현 성숙도를 자동 하향하지 않는다.

## 3. 제품·작업·관리 정본

| 문서 | 역할 | 수명주기 | 마지막 내용 검토일·범위 | 근거 기준·범위 | 재검토 trigger | 담당 도메인·후속 |
|---|---|---|---|---|---|---|
| [제품 이름](product_identity_and_naming_ko.md) | 제품 표시·호환 이름·영한 표기·역할 정본 | 활성 | 2026-10-09, Cellivane 채택·구성요소·온라인 이름 근거 | 조사일10-09; Cell+vane는 자체 naming intent·제한 미검출, 상표/도메인 미확정·code_import0 | 이름/표기/역할·공개 배포/등록·기술 migration·충돌 발견·외부 근거 재사용/30일 | 제품 identity; 표시 mirror와 사실 소유자 대조 |
| [제품 방향](aios_product_direction_ko.md) | 제품 목적·공간·상호작용·성공 기준 정본 | 활성 | 2026-10-09, 이름·역할 정본과 P1a 제품 관계 연결; 설치/심핵 출처 유지 | 목적·기존 실제 기록 보존; P1a PARTIAL·좁은/독립 fixture PASS·심핵/고권한/실기기 PLANNED | 사용자 목적·성공 기준 변경 | 제품 방향; 운용 계약·전역 큐에 영향 전달 |
| [통합 작업 진입](integrated_work_guide_ko.md) | 요청 분류·사실 소유자·변경 절차 | 활성 | 2026-10-09, naming·서빙P1a 진입 연결 | 라우팅만 대조; 자동 환경 발견·영속 기억 구현 아님 | 작업 규칙·도메인·정본 경로 변경 | 문서 운영; 진입 경로와 스킬 라우팅 대조 |
| [AGENTS](../../AGENTS.md), [프로젝트 스킬](../../.agents/README.md) | 작업 규칙·도메인별 절차 라우터 | 활성 | 2026-09-09, 제품 목적·전역 큐·신선도 연결 | 작업 규칙과 문서 동기화·triage·관리 구조·Linux 큐레이터 스킬; runtime 상태는 분야 정본에 위임 | 권한·작업 절차·도구·정본 경로 변경 | 저장소 운영; 관련 스킬의 규칙·링크 대조 |
| [전역 작업흐름](minimal_io_and_maturity_workflow_ko.md) | 유일한 전역 큐·기술축 성숙도 정본 | 활성 | 2026-10-12, Seed 선택; 브릿지/P1a/구조/P0/portable/round08 보존 | Seed SUPPORTING/PARTIAL·실제 CPU/cache/bridge 한정 PASS; 기존 public/이미지·portable/심핵 상태 유지 | 단계 완료·선행조건·사용자 우선순위 변경 | roadmap; `cellivane-seed-current`·보존한bridge/P1a·구조/P0·`portable-basic-next`·역사 큐 대조 |
| [자기 참조 연구·실증](self_reference_research_workflow_ko.md) | 실험·beta 이후 기존 GPT 검토·로컬 반영 운영 가이드 | 활성 | 2026-09-24, bfea/5bd CI·GPT06/07 범위·6응답/379파일 감사와 E0·QEMU 두 시도 대조 | RESEARCH/PARTIAL; 기존 실패 보존·STATIC_ONLY 개선 미관측; 새 Task 코드는 PREPARED, 실행은 두 번 FAIL | 실행·검증 결과, 실험 조건·모델 pin·연구 제안 채택 변경 | 연구·검증; 실제 artifact와 영향 mirror를 대조하고 원본 실패 보존 |
| [PROJECT](../../PROJECT.md) | 도메인 맵·의존 방향 정본 | 활성 | 2026-10-09, 격리 hosted/experimental·tools lab/verifier 책임 대조 | 브릿지 PARTIAL/RESEARCH·Linux public family/P1a 보존; runtime→tools 의존 없음 | 파일 이동·새 도메인·의존 경계 변경 | 저장소 구조; 각 도메인 README 연결 |
| [CLAUDE](../../CLAUDE.md) | 구현 mirror·빌드·저수준 불변식 | 활성 | 2026-10-09, 이름·P1a 현재 큐와 source closure mirror | AIOS 기술값·receipt3·공개 daemon 상한·public family 유지; P1a PARTIAL/좁은/독립fixture PASS | 명령·공개 계약·gate·구현 상태 변경 | 구현·검증; 변경 사실의 원 소유 가이드 대조 |
| [인수인계](codex_handoff_tips_ko.md) | 환경·장애 원인·검증 경계 운영 참고 | 활성 | 2026-09-13, v0.10과 최신 증거 정본 진입 대조 | native·hosted 역사 본문 유지; Windows 전체·Linux fixture와 한정 실제 모델 TaskSmoke PASS는 별도 | 실행 환경·명령·재현 조건 변경 | 작업 운영; 실제 현재 상태를 먼저 재확인 |
| [관리 모델](../kernel-room/kernel_room_management_model_ko.md) | 관리 의미·권위·불변식·분야별 의존 정본 | 활성 | 2026-10-08, 현재 전역 큐 링크만 정렬; 상세 계약 검토는 09-13 유지 | 관리 의미·native ABI 유지; P0 fixture는 canonical binding 아님 | identity·세대·관계·용어·관리 권위 변경 | Kernel Room; topology·개발 가이드 동기화 |
| [관리 개발 가이드](../kernel-room/development_guide_ko.md) | 관리 변경·검증 운영 가이드 | 활성 | 2026-10-08, 현재 큐 링크만 정렬; native/hosted 증거 검토는 09-13 유지 | native 계약·과거 실행 증거 유지; 새 관리 실행 검증 없음 | 개발 절차·검증 경로·관리 계약 변경 | Kernel Room; 작은 변경과 verifier 대조 |
| [관리 topology](../kernel-room/kernel_room_topology_ko.md) | 관리 정본에 종속된 개념도 | 활성 | 2026-09-03, 본문 갱신 기록 | hierarchy·identity·binding 설계; 독립 성숙도 정본 아님 | 관리 모델의 용어·관계 변경 | Kernel Room; 개념도와 정본 일치 확인 |
| [에이전트 운용 계약](../autonomy/agent_operating_contract_ko.md) | 상태·행동·거부·결과·복구 계약 | 활성 | 2026-10-08, shared Task 수명·unbound fixture·취소 범위 연결 | P0 PARTIAL; legacy v3·normalized envelope 분리·실제 서버/stream 미검증 | 상태 schema·행동·권한·사용자 개입·서버 pin/slot 설정 변경 | autonomy·hosted; 실제 소비·결과 검증은 전역 큐에서 선택 |

[저장소 문서 색인](../README.md), [Kernel Room 허브](../kernel-room/README.md),
[hosted 도메인 진입](../../hosted/README.md)은 2026-09-09 역할·경계 정비를 반영한
활성 색인이다. 저장소 문서 색인은 2026-09-13에 v0.10 Task와 증거 정본의 진입을
추가 대조하고 자기 참조 연구·실증 가이드의 진입을 연결했다. README·PROJECT·CLAUDE의
첫 실패·calibration 재생·v2 검사/grammar probe·후속 source와 미완료 행동 비교 경계도 함께 대조했다.
2026-09-24에는 연구의 고정 상태 6응답·독립 감사·현재 238개 검사, 5bd 게시/검토와
후속 증거 보고 Task의 코드 `PREPARED`와 실제 QEMU 두 시도의 FAIL을 같은 mirror와
문서 색인에 반영했다. 버전·테스트 수·source별 상세 결과는 위 정본과 아래 가이드가 소유한다.
새 문서·도메인·실행 경로가 생기면 연결을 함께 대조한다.
2026-10-09에는 README·docs 색인·hosted 진입의 Cellivane 표시 이름과 구성요소 역할,
P1a 내부 입구·source closure 분리의 링크를 대조했다. 원본 source·로그·상한·AIOS 기술
field는 유지하며 P1a의 새 실행 결과는 서빙§9의 source별 판정과 연결한다.
2026-10-08 후속에는 README·docs 색인·hosted 진입에 공식 구조 비교와 좁은 내부 책임
분리의 링크·상태를 동기화했다. 내용 검토와 새 실행 판정은 별개이며 제품·native·
KernelRoom 명세 자체는 이 후속에서 변경하지 않았다.
2026-10-08 SERVE-P0에서는 저장소 문서 색인·hosted 도메인 진입에 서빙 정본을 추가하고,
Kernel Room 허브·관리 가이드·브라우저 roadmap의 현재 큐 링크만 정렬했다.
각 분야의 구현·과거 실행 증거를 전체 재검증한 것은 아니다.
hosted 도메인 진입과 Kernel Room 허브는 2026-09-13에 v0.10 Task의 문맥·취소 경계를
추가 대조했다. 이 체크포인트의 v0.10과 보존된 v0.9·기존 beta·이미지 기록을 구분하며, 보존된 실제 문맥
소비/fixture와 한정 실제 모델 Task PASS·미완료 새 이미지의 증거를 분리한다.

## 4. 실행·검증 가이드

아래의 날짜는 각 가이드가 명시한 내용·근거 시점이다. 실행 ID, 정확한 명령, 버전,
해시, 성공과 실패의 원본은 각 가이드가 소유하며 이 원장에 중복하지 않는다.

| 문서 | 역할 | 수명주기 | 마지막 내용 검토일·범위 | 근거 기준·범위 | 재검토 trigger | 담당 도메인·후속 |
|---|---|---|---|---|---|---|
| [Linux 실행 기반 정책](../os/linux_hosted_substrate_and_resource_policy_ko.md) | 실행 기반·source 반입 경계 정본 | 활성 | 2026-10-08, 현재 큐·서빙 정본 진입만 연결; 상세 검토 09-13 유지 | upstream exact reference 확인은 **2026-08-23** 유지; P0는 source-only/code-import 정책 변경 아님 | 실행 책임·반입 정책 변경; upstream 작업 착수/30일 | hosted·Linux resource; 공식 근거와 manifest부터 대조 |
| [H1 trace/replay](../os/h1_binding_trace_replay_workplan_ko.md) | bounded H1 계약·검증 정본 | 활성 | 2026-09-03, 보존된 원격 acceptance | host-only 계약/replay 증거; live producer·H2 runtime 제외 | H1 field/reason/lifecycle·bundle·checker 변경 | hosted·testkit; 해당 source의 재생 계약 확인 |
| [부팅·하드웨어](../os/aios_userspace_boot_hardware_guide_ko.md) | 시작 로그·Linux-visible inventory 운영 가이드 | 활성 | 2026-09-08, 운영 mirror; 공식 검토는 09-03 | 보존된 source 관측·실행별 artifact; native 드라이버 지원 아님 | bootstrap·inventory·권한·source/검증 변경 | hosted; boot 계약과 실제 관측 대조 |
| [CLI·인터넷](../os/aios_cli_internet_guide_ko.md) | 고유 CLI·DNS/HTTP(S) 실행 가이드 | 활성 | 2026-09-13, v0.10 UUID 질문 흐름 연결; 공식 검토는 09-03 유지 | 보존된 기존 CLI·인터넷 증거와 새 Task의 실제 모델 검증을 구분 | 명령·네트워크 계약·launcher 변경 | hosted; CLI 사용법·session 판정 대조 |
| [일반 서비스](../os/aios_service_lifecycle_guide_ko.md) | CONSOLE_RUNTIME 수명·재접속 계약 | 활성 | 2026-09-04, 본문 공식 검토 기록 | 서비스 기반과 실제 MAIN AI_SERVICE를 구분 | 서비스 수명·identity·receipt·재접속 변경 | hosted; source와 service verifier 대조 |
| [MAIN 결속](../os/aios_agent_binding_guide_ko.md) | 실제 모델 요청·명시적 관리 결속 계약 | 활성 | 2026-09-13, v0.10 개발 경계 연결; 본문 실행 기록은 09-07 유지 | 당시 결속·모델 실행과 후속 문맥·Task 검증의 source를 구분 | MAIN protocol·binding·모델 profile 변경 | hosted·Kernel Room; 모델 응답과 실행 증거 구분 |
| [MAIN 환경 문맥](../os/aios_space_context_guide_ko.md) | 환경 관측·신선도·실제 모델 입력과 소비 검증 정본 | 활성 | 2026-10-08, source43·legacy 어댑터/fixture 경계 연결 | PARTIAL; v0.10 TaskSmoke PASS와 새 P0 fixture·E0 QEMU FAIL·이미지 미완료를 분리 | 관측 범위·TTL·입력·receipt·모델 실행·실제 검증 결과 변경 | hosted·autonomy·testkit; raw→입력→실행→사용자 출력과 거부·복구 대조 |
| [자원 관측](../os/aios_resource_observation_guide_ko.md) | MAIN/backend 관계·CPU/RSS·PSI 관측 | 활성 | 2026-09-13, v0.10 개발 경계 연결; 본문 근거는 09-07 유지 | 당시 source 관측 증거 유지; Task 자원 창과 모델 계산 귀속을 구분 | 관계·관측 필드·source 유효성 변경 | hosted·resource; 관측과 제어 주장 분리 |
| [Cell 수명](../os/aios_cell_lifecycle_guide_ko.md) | 한정 Cell 관리 전이·재결속 계약 | 활성 | 2026-09-13, v0.10 개발 경계 연결; 본문 근거는 09-07 유지 | 당시 관리 세대 전이·거부 증거 유지; 전체 hierarchy·Task acceptance와 별도 | 관리 상태·세대·reconcile 변경 | Kernel Room·hosted; 해당 세대 전이와 verifier 확인 |
| [backend 수명](../os/aios_backend_lifecycle_guide_ko.md) | 실행 대상 결속·같은 CLI의 recover | 활성 | 2026-10-08, legacy 어댑터·backend run2/source19·fixture 취소 범위 | 기존 retained handle·stop 의미 보존; attached fixture는 backend stop 권한 없음·새 실제 실행 없음 | backend identity·owner lease·receipt·recover 변경 | hosted; 허용된 cleanup·정상 종료 경계 확인 |
| [서빙 개발 계약](../os/aios_serving_design_ko.md) | 엔진 어댑터·capability·normalized Task 증거 정본 | 활성 | 2026-10-09, P1a 한도·active1 공개 경계·public32/전용33·candidate44 대조 | P1a PARTIAL·31/77/28/7 PASS·4종독립CLI33 PASS; 전체판정은§9·실제Ollama/이미지 NOT_RUN; 원본P0/구조 증거 보존 | adapter·capability·Task 수명·inventory·verifier·실행 판정 변경 | hosted·tools; §9의 source별 독립 판독·현재 회귀 대조 |
| [Cellivane 엔진 조율](../os/cellivane_engine_orchestration_ko.md) | 다중·병렬·다층·게임 IPC의 bounded 후속 설계 | 활성 | 2026-10-09, 색인·서빙 후속 진입 연결 | PLANNED; actual P1a 검증은 서빙§9에 위임·shared memory/native 실행 증거 아님 | 조각 선택·admission/IPC/authority 계약·실행 판정 변경 | hosted·native; 전역 큐에서 선택하고 source별 proof 분리 |
| [Cellivane 브릿지 실험](../os/cellivane_bridge_experiment_ko.md) | 격리 기준/보조 runtime·D: lab·독립 journal/actual 판정 | 활성 | 2026-10-09, 코드·원문·소유 Job·Strata 지원 조사 대조 | PARTIAL/RESEARCH; actual 소형 llamafile/Ollama와 품질 오답 구분·Strata UNKNOWN/generation0·전체 목표 미완료 | 역할/예산·transport·소유 수명·Strata qualification·실행/품질 결과 변경 | hosted/experimental·tools; source/hash·raw journal·독립 판독·원본 실패 유지 |
| [Cellivane Seed](../os/cellivane_seed_engine_ko.md) | 자체 scheduler·정확한 cache·합류·HTTP·작은 모델 실험 정본 | 활성 | 2026-10-12, source13·실제 CPU/cache·bridge 호환과 Strata 고정 자료 대조 | SUPPORTING/PARTIAL; 한정 실제 PASS·품질 개선 없음·최종 회귀는§6·no MTP/KV sharing | runtime·identity/cache/admission·공식 pin·source·실제 실행 결과 변경 | hosted/experimental·tools; 신규 source/원문/독립 판독과 기존 bridge/public family 분리 |
| [공식 구조 비교·채택](../os/aios_architecture_comparison_20261008_ko.md) | upstream 비교·후속 결정과 source별 검증 참고 | 활성 | 2026-10-08, 공식 URL/라이선스 범위·shadow 재현/수정·최종 회귀/독립 fixture 대조 | 자료 RESEARCH/code_import0·pin 미확보; 후속 PARTIAL·새 회귀/독립 fixture PASS·성능/실제 서버/이미지 미실행 | 참조 착수/30일·upstream 내용/라이선스 변경·채택 코드/실행 판정 변경 | hosted·docs; 원본P0와 새 source32 증거 분리·전역 큐에서 후속 선택 |
| [운영 이미지](../os/aios_operating_image_guide_ko.md) | 설치·반복 부팅·기본 선택·acceptance 정본 | 활성 | 2026-09-13, v0.10 개발 경계 연결; 공식 자료·운영 근거는 09-08 유지 | 보존 이미지별 원본 증거 유지; source 39개 신규 이미지와 부팅 시 backend 소유 handle 분석 미완료 | Build/Smoke/Run·selector·installer·OS lock·pin 변경 | hosted·Windows; 원본/사용자 사본·실행 도구 범위 확인 |
| [검증 설계](../tools/verification_tooling_evolution_design_ko.md) | verdict·evidence·provenance 정본 | 활성 | 2026-09-03, 본문 최종 갱신 기록 | 정규 lane과 진단 lane 분리; 설계된 후속 기능은 별도 | verdict·artifact·baseline·CI 판정 계약 변경 | testkit; fail-closed와 증거 출처 대조 |
| [Testkit](../tools/testkit_guide_ko.md) | 실제 검증 명령·결과 사용 가이드 | 활성 | 2026-09-13, 동기 SpaceSmoke·후속 TaskSmoke의 계약 분리 | 보존 source별 판정 유지; 새 smoke 구현은 실제 모델 성공 증거가 아님 | 명령·테스트 진입·platform·artifact 경로 변경 | testkit·hosted; 새 실행과 보존 원본 재검증 구분 |
| [QEMU MCP](../tools/qemu_mcp_guide_ko.md) | 진단 편의 도구 운영 가이드 | 활성 | 2026-08-28, 도입 기준 기록 | 등록·도구 노출도 당시 환경의 기록; 정규 verdict 아님 | 실제 도구 사용 착수·등록/버전 변경·외부 근거 30일 | 개발 도구; 현재 등록·노출 상태를 직접 확인 |

로컬 `build/`와 이미지 원본은 비추적 증거다. fresh checkout에서 파일이 없다는 이유로
이전 PASS를 현재 재생했다고 쓰지 않는다. 반대로 과거 이미지의 source bytes가 현재 파일과
다르면 그 원본의 보존 runtime으로 재생하고, 새 source의 검증 여부는 별도로 기록한다.
원본 FAIL을 사후 PASS로 덮거나 문서 날짜에 맞추어 원본 artifact를 바꾸지 않는다.

## 5. 분야별 후보·참고·외부 조사

다음 문서는 후보·설계·당시 조사 맥락을 제공한다. 현재 제품 방향과 충돌하는 문장을
그대로 구현 지시로 사용하지 않는다. 외부 주장이 필요한 경우에만 §2의 공식 자료 재검토를
수행하며, 조사 날짜를 이번 문서 정비일로 덮지 않는다.

| 문서 | 역할 | 수명주기 | 마지막 내용 검토일·범위 | 근거 기준·범위 | 재검토 trigger | 담당 도메인·후속 |
|---|---|---|---|---|---|---|
| [빌드 프로젝트 조사](aios_build_project_landscape_2026_08_03_ko.md) | 외부 사례 참고 | REVIEW | 2026-08-10, 구현 경계 대조 기록 | 외부 조사는 **2026-08-03**, RESEARCH | 비교·도입 작업 착수 또는 외부 근거 30일 | 도구·제품 조사; 선택한 사례의 현재 1차 자료 확인 |
| [과거 AI-native OS 조사](ai_native_os_github_landscape_ko.md) | 역사적 외부 조사 | OLD | 2026-04-21, 조사 기록 | 당시 공개 프로젝트 스냅샷 | 새 비교 근거로 재사용할 때 | 제품 조사; 당시 결론 보존하고 새 공식 근거를 별도 기록 |
| [모델 스택 추천](../models/agent_model_stack_recommendations_ko.md) | 모델·학습 전략 참고 | REVIEW | 2026-09-09, 분류·내용 경계 | 원문 기재 기준은 **2026-03-28**, 출처별 실제 확인일은 미확인; 모델·라이선스·조합의 현재성도 재검증하지 않음 | 모델 선택·다운로드·학습 착수 또는 외부 근거 30일 | 모델·runtime; 실제 목적·하드웨어와 공식 자료로 재평가 |
| [초기 자율 OS 요구](../os/ai_agent_autonomous_os_requirements_ko.md) | 초기 native 요구 참고 | REVIEW | 2026-09-09, 분류·내용 경계 | 기존 기술 내용의 원 검토일 미기록; 초기 경로·기능 부재 전제는 현재 계약 아님 | 요구 재사용·현재 제품 계약으로 반영할 때 | autonomy·native; 제품 정본·운용 계약과 충돌 분리 |
| [품질 backlog](maturity_levers_backlog_ko.md) | SUPPORTING/ORTHOGONAL 품질 후보 | 활성 | 2026-09-09, 후보와 역사 구분 | 당시 진단·이전 다음 단계는 보존 기록; 현재 전역 큐 아님 | 해당 후보를 실제 작업으로 선택할 때 | 검증·품질; 현재 gap 재현 후 전역 큐에서 우선순위 판단 |
| [브라우저·runtime roadmap](../os/browser_console_and_runtime_engine_roadmap_ko.md) | W 분야의 브라우저 전달 설계 가이드 | 활성 | 2026-10-08, 현재 큐 링크만 정렬; 상세 W 검토 09-13 유지 | hosted 개발 소스와 W의 PLANNED/RESEARCH는 별도; 브라우저 구현 검증 아님 | W 기능·browser adapter·engine 작업 착수 | W·autonomy; 실제 소비 계약·현재 구현 경계 대조 |

역사 기록을 삭제하거나 모두 활성으로 다시 쓰는 것이 신선도 관리의 목표는 아니다.
현재 결정에 쓰는 사실의 소유자와 유효 범위를 찾을 수 있고, 필요한 부분을 다시 검토할 수
있으면 된다. `REVIEW`의 정정·재분류가 필요할 때는 본문 배너·색인·이 행을 같은 작업에서
맞추며, 전역 구현 큐의 변경은 전역 작업흐름에서 별도로 결정한다.

## 6. 한 번의 갱신을 마치는 방법

1. 현재 변경이 영향을 주는 사실 소유 문서를 고르고 실제 본문·코드·근거를 대조한다.
2. 확인한 주장, 확인하지 않은 범위, 실행/외부 근거의 날짜를 분리해 적는다.
3. 해당 행의 내용 검토일·범위와 trigger·담당 후속을 갱신한다. 역할 변경은 배너와 색인도 맞춘다.
4. 중복 수치·결론을 다른 문서에 늘리지 않고 소유 문서로 연결한다. 링크와 변경 범위를 확인한다.

문서만 바꾼 작업에는 그 사실을 남기고 종료한다. 새로운 runtime 성숙도, 자동화된 신선도
검사기, 영속 AI 기억 또는 통합 공간 인지 기능이 구현됐다고 보고하지 않는다.
