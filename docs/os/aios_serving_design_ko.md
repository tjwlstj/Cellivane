# Cellivane · 셀리베인 엔진 어댑터와 서빙 개발 계약

> 문서 역할: hosted 엔진 어댑터·서빙 개발의 계약과 채택 범위 정본
>
> 문서 수명주기: 활성
>
> 내용 검토일: 2026-10-09 — Cellivane 표시 이름·SERVE-P1a 채택 범위와 source closure 연결; P0·구조 후속의 원본 증거는 §6/§8에 보존
>
> 구현 성숙도: P0·구조 후속·P1a 개발 `PARTIAL`; P1a 좁은 회귀·HTTP fixture 독립 판독·Windows 전체 hosted 회귀는 §9의 범위에서 PASS다. 실제 두 서버·streaming·운영 이미지 acceptance는 `PLANNED`다.
>
> 상위 정본: [제품 방향](../meta/aios_product_direction_ko.md), [제품 이름](../meta/product_identity_and_naming_ko.md), [전역 작업흐름](../meta/minimal_io_and_maturity_workflow_ko.md#serve-p1a-current), [Kernel Room 관리 모델](../kernel-room/kernel_room_management_model_ko.md), [Linux 실행 기반 정책](linux_hosted_substrate_and_resource_policy_ko.md)

Cellivane은 제품 표시 이름이며 AIOS module·wire 제품 field·CLI·receipt·ABI와 보존된
source/artifact 이름은 기술·호환 계약으로 유지한다. Engine은 deployment별 모델 실행기와
어댑터 역할이며 Chesi 동반자나 Kernel Room 관리 identity를 대신하지 않는다.

2026-10-12 현재 선택인 [Cellivane Seed](cellivane_seed_engine_ko.md)는 독립 scheduler·정확한 결과 cache·동일 flight 합류다(`SUPPORTING`/`PARTIAL`).
token 계산은 외부 pinned llamafile CPU worker이며 실제 CPU/cache·기존 bridge 호환은 한정 PASS다. 품질 향상은 없고 최종 회귀는 Seed§6이 소유한다.
공개 P0/P1a source family·MAIN 관리 binding·native ABI·이미지 acceptance에 이 실험을 승계하지 않는다.

2026-10-09 사용자가 추가로 선택한 [다중 엔진 브릿지 실험](cellivane_bridge_experiment_ko.md)은
`hosted/experimental`의 별도 초기 프로그램이다. 실제 llamafile/Ollama 소형 모델과 D:
실험 증거를 이 문서의 P0/P1a public Task·source family·이미지 acceptance에 승계하지 않는다.
Strata 기준 route는 실제 qualification 부재로 차단하며 상세 actual·품질·정리는 실험 정본이 소유한다.

## 1. 채택한 작업과 출처

2026-10-08 사용자는 제공한 서빙 설계·인계를 새 세션에서 현재 구현과 대조하고,
가장 작은 구현 조각 `SERVE-P0`를 구현·검증하도록 요청했다. 인계 문서 안의
“로컬에서 채택할 경우”는 문서 작성 당시의 조건부 제안이다. 이번 요청이 P0의
개발 권한을 제공하며 원격 게시·운영 이미지 교체·다른 GPT 대화 전송까지 포함하지 않는다.

대조한 입력은 다음 두 파일이다. 이 파일의 외부 엔진 조사·과거 판정은 이번 실행
증거가 아니며, 외부 제품의 현재 기능을 여기서 다시 검증한 것도 아니다.

| 입력 | 확인한 SHA256 |
|---|---|
| `AIOS_SERVING_DESIGN_2026-10-08.md` | `D4EB076C27DC5BC16DBAE334CAE9A19A022BC406D05691C40FBC583F0E2DD2D5` |
| `AIOS_SERVING_CODEX_HANDOFF_2026-10-08.md` | `0D70887F9562A05329CFFF72C8BB43A5FAC98A760DEFCAE29857668D70C19B12` |

구현 기준은 `origin/beta`의 `7d47524867e5f3d49521a0a5f7b1d0e65b5fe395`에서
분리한 `work/serve-p0-20261008`이다. 기존 ROOT의 사용자 수정과 ego 방향 worktree의
미커밋 문서는 이 변경에 통째로 흡수하지 않았다. 2026-09-29 로컬 제품 방향의
심핵·위임된 높은 권한의 로컬 LLM·다중 하드웨어 설치 목표는 제품 정본과 전역 큐에
출처와 미완료 경계를 기록한다. P0는 그 목표를 완료하지 않는다.

이번에 채택한 것은 **기존 pinned 요청을 보존하는 어댑터 경계, 최소 배포·기능 계약,
두 번째 프로토콜 fixture와 동일 Task 수명 경로의 연결**이다. 설계안의 전체
HTTP facade, 자동 라우팅, 자원 배치 정책과 자체 엔진을 구현 대상으로 승계하지 않는다.
Kernel Room에는 `SUPPORTING` 기여이며 새 canonical Node/Cell 결속을 만들지 않는다.

## 2. 기존 코드의 책임과 새 경계

| 코드 | 유지하거나 분리한 책임 |
|---|---|
| `hosted/linux/aios_agent/inference.py` | 기존 config·입력·응답 상한, worker transport와 legacy receipt v3 유지; 엔진별 wire 직렬화와 응답 검증은 어댑터에 위임 |
| `hosted/linux/aios_agent/request_state.py` | 단일 요청의 전이·결과와 strict legacy receipt v3 검증; nonlegacy normalized 증거와 구별 |
| `hosted/linux/aios_agent/request_runtime.py` | 접수/취소 durable 저장, dispatch·finalize 순서, 단일 writer·poison 경계 유지 |
| `hosted/linux/aios_agent/daemon.py` | Task/event 상한과 전역 active 1 유지; 새 어댑터 연결 때문에 동시성을 확대하지 않음 |
| `hosted/linux/aios_agent/backend_binding.py` 및 `aios_backend/client.py` | service/instance/start_generation과 보유 handle 기반 legacy 실행 대상·정지 권한 유지 |
| `hosted/linux/aios_engines/` | 엔진·배포·기능의 최소 계약, legacy llamafile 및 messages fixture의 직렬화·응답 검증 |
| `tools/hosted/`의 source inventory·manifest·verifier·tests | 새 runtime source의 snapshot·독립 증거 검증과 기존 버전 family의 보존 |

EngineSpec v1은 `adapter_kind`·`wire_protocol`·`evidence_kind`를 표현하는 최소 내부
계약이다. 실제 엔진 binary/version을 검증했다고 주장하는 일반 registry가 아니다.
Deployment는 엔진·`model_id`·`service_id`·`instance_id`·`start_generation`과
`managed`/`attached` ownership을 연결한다. CapabilityReport는 이 배포에 결속되어
`text_completion`·`messages`·`streaming`·`usage`·`request_cancel`을 기능별
`supported` / `unsupported` / `unverified`를 구별한다. 엔진의 기능 광고는 supervisor의
소유 handle나 stop 권한을 대신하지 않는다. 확인할 수 없는 artifact digest·backend
identity·usage·메모리 반환은 unknown으로 남긴다.

messages 요청은 필수 capability를 제출 전에 검사한다. 미지원·미확인이면 backend
제출은 0회여야 한다. P0는 실제 wire request/response bytes와 AIOS가 계산한 digest를
보존한다. 별도의 일반 canonical request schema·digest registry는 아직 없다.
wire evidence의 digest는 AIOS가 관측한 사실이며 엔진이 echo/hash를 제공했다는 주장이 아니다.

## 3. P0의 두 프로토콜

| 어댑터 | 요청·응답 계약 | 증거 범위 |
|---|---|---|
| `LegacyLlamafileAdapter` | 기존 Qwen ChatML·`/completion`·`stream=false`·상한·prompt echo 검사, 기존 request bytes와 오류 vocabulary 보존 | 기존 legacy receipt schema 3·backend/관리 binding을 그대로 검증 |
| messages fixture | 역할을 가진 `messages` 입력; ChatML을 요구하지 않으며 정상 응답에 prompt echo 없음 | 별도 normalized envelope와 실제 fixture 응답 검증; artifact·process·canonical 관리 binding을 합성하지 않음 |

messages fixture는 실제 llama.cpp/Ollama/vLLM 서버가 아니다. 이 프로토콜의 Task는
기존 MAIN의 관리/backend binding을 상속하지 않는다. 공유하는 것은 durable Task의
수명 규칙이며 legacy validator의 검사를 느슨하게 만들어 호환성을 얻지 않는다.
stream/usage 등의 필수 기능을 미지원 또는 미확인으로 고정해 거절 경로를 검증한다.

P0의 messages 진입은 `RequestExecution.for_messages(...)`다. 새 CLI/RPC engine
선택 기능이나 HTTP chat endpoint를 공개하지 않으며, 실제 single-writer execution·
shared RequestState와 bounded subprocess worker를 이용한다. Task의 MAIN source·
management·backend_expected는 unbound로 두고 normalized envelope 1로 완료 증거를
검증한다. 이 envelope는 legacy receipt 3이 아니며 echo/관리 binding을 합성하지 않는다.

## 4. 보존할 수명 불변식

1. durable 접수 이후 dispatch하고, durable 취소 의사 이후 취소를 전달한다. 조회는
   재제출·재계산·상태 mutation을 만들지 않는다. 한 writer가 terminal을 한 번만 확정한다.
2. persistence/finalizer failure는 producer를 poison한다. 실패를 재제출이나 성공 결과로
   숨기지 않는다. dispatch 전 취소의 `NOT_STARTED`와 제출 여부 불명의 `UNKNOWN`을 구별한다.
3. 취소 의사 뒤 유효 receipt가 도착하면 legacy `ANSWERED`가 가능하다. backend_stop은
   model_outcome을 덮어쓰지 않는다. 늦은 유효 결과를 취소 표시에 맞추려고 삭제하지 않는다.
4. 결과, worker 종료, backend 종료, delivery 취소, 모델/KV 메모리 반환은 별도 사실이다.
   worker timeout이나 연결 EOF만으로 backend 종료·취소 성공·메모리 반환을 확정하지 않는다.
5. service/instance/start_generation과 실제 보유 handle를 존중한다. 오래된 callback,
   finally/cleanup/stop은 교체된 instance에 영향을 주지 못한다.
6. 요청 취소와 whole-instance stop은 별도 operation이다. 공유 엔진의 요청 취소에
   legacy owned backend kill/unload를 연결하지 않는다. messages fixture의 취소로
   legacy backend stop을 호출하지 않는다.
7. 기존 active 1·Task 16·event 64 상한을 유지한다. 큐·stream buffer·in-flight 정책의
   일반화와 한도 확대는 별도 acceptance 조각이다.

P0에는 streaming 출력 fence가 없다. P0의 취소 뒤 결과 보존을 streaming의 신규 출력
차단까지 검증한 것으로 보고하지 않는다. restart 이후 자동 입양·retry·continuation이나
exactly-once backend 실행도 제공하지 않는다.

## 5. source 및 과거 증거의 경계

새 `aios_engines` runtime source는 실제 사용하는 MAIN/CLI source inventory,
운영 이미지 manifest와 독립 verifier 목록에서 함께 검사한다. source digest가 달라지면
기존 source snapshot·운영 이미지 PASS가 새 bytes를 검증했다는 의미가 되지 않는다.
legacy receipt 3과 기존 backend identity 계약은 adapter 추출만으로 새 schema로 바꾸지 않는다.
P0의 정확한 inventory와 검사 결과는 §6의 원본 실행 기록에서 정한다. P1a의 optional
closure와 새 source/hash는 §9에서 분리한다.

P0·구조 후속의 inventory 계약은 MAIN protocol 6/run 7/source 32, backend protocol 1/run 2/source 19,
CLI 0.11.0/session 11/source 39, 전체 hosted Python source 43이다. 신규 어댑터 package의
네 파일을 runtime snapshot에 포함하고 과거 source family를 별도 유지한다. source43
운영 이미지 manifest는 후보이며 실제 이미지 검증은 아직 지원·실행하지 않는다.

현재 CLI session 11의 EvidenceReport QEMU producer를 역사적
`tools/hosted/evidence_report_contract.py`의 schema 10 validator와 결합하는 경로도
아직 미지원이다. 기존 schema 10 fixture는 보존하며 P0에서 그 역사 계약을 확장하거나
실제 QEMU EvidenceReport를 다시 실행하지 않았다. TaskSmoke guest의 event reader만
session 10/11을 읽고 한 실행 안에서 session의 일관성을 검사하도록 현재 source
verifier와 연결한다. 이는 source43 운영 이미지나 EvidenceReport11의 runtime
qualification을 완료한 증거가 아니다.

기존 source 35/36 이미지와 v0.10 source 39 이미지의 역사·미완료 acceptance를 유지한다.
이 조각은 운영 이미지를 생성하거나 교체하지 않는다. native kernel/QEMU, GPU driver,
Linux source-only manifest의 code-import 정책과 리소스 observation_only는 변경하지 않는다.

입력 설계·인계에 기록된 **round08 저장·재읽기 시점의 독립 증거 부족 P2는
유효·미수정으로 닫힌 과거 판정**이다. 이번에는 해당 대화나 CI를 재감사하지 않았고,
P0의 새 event/adapter 증거가 그 저장·재읽기 효과를 수정·입증하지 않는다.
연구 원본 FAIL, 첫 pilot/ON-OFF NOT_EVALUABLE, STATIC_ONLY 개선 미관측과
evidence-report-feedback-v1의 실제 QEMU 두 시도 FAIL도 그대로 보존한다.

## 6. 검증 기록

2026-10-08 Windows Python 3.11.9에서 아래 좁은 회귀를 실행했다. 현재 결과는
**Windows hosted 전체1055(실행970 PASS·skip85), legacy·messages fixture의 한정 PASS**다.
이후 독립 verifier 응답 상한의 마지막 수정은 별도 11개 검사와 현재 CLI의 재판독으로 PASS를 확인했다.
최초 전체 검사 실패 로그도 보존한다. 검사군은 서로 겹치므로
표의 수를 합산해 전체 검사 수로 사용하지 않는다.

| 검증 | 현재 판정 | 확인할 경계 |
|---|---|---|
| legacy request bytes·receipt v3·오류 회귀 | `PASS` | 107 수집·104 실행 PASS·Linux 전용 3 skip; [로그](../../build/serve-p0-20261008/legacy-regressions.log) |
| messages fixture와 실제 Task 수명 | `PASS` | 17 PASS; 실제 bounded subprocess의 echo 없는 응답·unbound Task 저장 callback; [로그](../../build/serve-p0-20261008/messages-regressions-final.log) |
| capability 미지원/미확인 | `PASS` | messages 17개 중 부정 사례; worker 제출 0회 |
| 저장 callback 실패·취소/결과 경합·terminal once-only | `PASS` | messages/legacy 회귀의 제어 가능한 실패 fixture·mock; Linux durable file/crash 검증은 별도 미실행 |
| 독립 fixture verifier 최종 회귀 | `PASS` | 전체 회귀 뒤의 11 PASS·0.204초; [최종 로그](../../build/serve-p0-20261008/fixture-verifier-regressions-final.log); 응답 16384 bytes 허용·16385 거절·Unicode byte/overflow 부정 사례 포함. 이전 [10개 로그](../../build/serve-p0-20261008/fixture-verifier-regressions.log)도 보존 |
| H1 Git trust 회귀 | `PASS` | exact per-command Git trust 조건을 고친 37 PASS; [로그](../../build/serve-p0-20261008/h1-trust-corrected.log) |
| Linux source-only resource guard | `PASS` | schema1·resource13·code_import0 유지; [로그](../../build/serve-p0-20261008/linux-resource-guard.log); upstream code import/새 실행 지원 판정 아님 |
| 수정 뒤 hosted 전체 회귀 | `PASS` | 1055 수집·970 실행 PASS·85 skip·332.954초; [최종 로그](../../build/serve-p0-20261008/full-hosted-regressions-corrected.log); 뒤의 pure-verifier 상한 수정은 별도 narrow 검사 |
| Linux process fixture·durable file/crash proof | `BLOCKED_ENV` / `NOT_RUN` | WSL 조회 exit1·`Wsl/CallMsi/Install/REGDB_E_CLASSNOTREG`; Windows skip를 Linux PASS로 계산하지 않음 |
| 실제 pinned 모델 실행 | `NOT_RUN` | 기존 실제 모델 PASS의 승계 금지 |
| CLI11 EvidenceReport QEMU 통합 | `NOT_RUN` | 현재 schema10 validator와 결합 미지원; 역사 fixture/FAIL 보존 |
| 실제 llama.cpp/Ollama·stream·GPU | `NOT_RUN` | SERVE-P1 이후 필수 통합 증거 |
| 새 운영 이미지·native QEMU·실기기 설치 | `NOT_RUN` | 이번 P0 범위 밖 |

첫 hosted 전체 검사는 1035 수집·323.823초·FAIL 4·ERROR 18·skip 85였다.
[원본 실패 로그](../../build/serve-p0-20261008/full-hosted-regressions.log)를 보존한다.
H1의 ERROR17/FAIL3은 linked NAS Git metadata의 trust 조건 문제로, trust 조건을
명시한 37개 재검사는 PASS였다. backend recovery의 ERROR1/FAIL1은 역사 source15를
새 source19 전용 검사에서 거절한 실제 회귀였다. source15/source19의 명시적 허용과
동일 start join을 보존하도록 수정하고, 관련 image runtime 검사는 20개 중 실행11
PASS·Linux 전용9 skip였다. 수정 뒤 전체 검사는 별도로 1055개를 실행해 PASS를
확인했으며, 위 좁은 검사 수와 합산하지 않는다. 마지막 pure-verifier 상한 수정은
그 전체 실행 뒤에 이루어져 최종 narrow 검사와 현재 CLI 독립 판독을 별도로 남긴다.

초기 [독립 판정](../../build/serve-p0-20261008/messages-independent-verdict.json)은
source32·snapshot3·model_outcome ANSWERED의 fixture PASS다. 해당 판정은
`real_engine_compatibility=false`와 `process_liveness_verified=false`를 유지한다.
초기 source bundle과 최종 [source manifest](../../build/serve-p0-20261008/final/source-manifest.json)·
[raw artifact](../../build/serve-p0-20261008/final/messages-task.json)는 별도로 보존한다.
먼저 저장한 [bundle 독립 판정](../../build/serve-p0-20261008/final/messages-independent-verdict.json)도
source32·snapshot3·ANSWERED의 fixture PASS이며 같은 두 false 경계를 유지한다.
이후 검토에서 reseal한 16KiB 초과 response를 독립 verifier가 허용하는 상한 불일치를
재현했다. verifier 상한을 runtime의 16384 bytes와 일치시키고 후속 11개 부정/정상
검사 및 [최종 현재 CLI 판정](../../build/serve-p0-20261008/final/messages-independent-verdict-final.json)을
PASS로 확인했다. 최종 판정도 source32·snapshot3·ANSWERED의 fixture PASS이며
실제 엔진 호환·process liveness 두 false 경계를 유지한다. 이전 verdict는 보존하며
이 마지막 수정의 완료 판정으로 사용하지 않는다. 마지막 변경은 독립 verifier/tools에
한정되며 MAIN runtime source32와 그 manifest hash는 바뀌지 않았다.
최종 source manifest SHA256은 `4AEE36769ADC8837263126BEC75212F6F1020EDC6905CCD3D4C507EF245B505F`,
raw artifact SHA256은 `C497B96AA7C1A618C1E53739657F7A5C0F97E09FF953557BA6AA5224630AC46A`다.
수정 뒤 전체 회귀는 1055개·85 skip PASS이며 후속 pure-verifier 11개·최종 CLI 판정도 PASS다.
`build/` 자료는 로컬 비추적 증거이며
Git commit에 자동 포함되지 않는다.

경합은 Event/barrier와 제어 가능한 fixture로 순서를 고정한다. 단순한 sleep 순서나
unittest 종료 코드 0만으로 Linux/실제 모델 acceptance를 주장하지 않는다. producer
evidence와 독립 verifier verdict의 책임을 구별한다.
실제 Task worker를 실행한 증거와 save callback의 순서/예외를 제어한 단위 검사는
구별한다. Linux 파일 저장의 durability, process crash 각 지점과 재시작 조정은 이번에
검증하지 않았다. 실제 모델·실제 두 서버·운영 이미지·QEMU·GPU 실행도 없다.

최종 독립 판독의 실행 명령은 다음과 같다. source snapshot과 raw artifact를 함께
읽으며 live process의 존재를 판정하지 않는다.

```powershell
py -3 -B tools/hosted/verify_engine_fixture.py --artifact build/serve-p0-20261008/final/messages-task.json --source-manifest build/serve-p0-20261008/final/source-manifest.json --source-root build/serve-p0-20261008/final/runtime-source
```

관련 회귀의 재현 진입은 `py -3 -B -m unittest discover -s tools/hosted/tests -p
"test_*.py" -v`이며 messages와 마지막 verifier는 각각 `test_hosted_engine_messages.py`,
`test_hosted_engine_fixture_verifier.py`로 좁힐 수 있다. linked NAS Git metadata를
읽는 H1 검사는 실제 root/worktree의 exact per-command trust 조건도 필요하다.
원격·global safe.directory를 광범위하게 바꾸는 작업으로 해석하지 않는다.

## 7. 다음 한 조각

P0의 fixture·회귀 검증 이후 전체 `SERVE-P1`은 버전을 고정한 실제 llama.cpp managed
deployment와 Ollama attached deployment를 공통 입구에서 순차로 연결하는 후보다.
모델 목록·명시적 모델 선택·텍스트 chat·stream·Task 조회와 요청별 취소, 늦은 callback·
부분 출력 실패·연결 유실을 실제 두 서버로 검증해야 한다. 초기 global active 1을
유지하며 external 연결을 process stop 권한으로 해석하지 않는다.

현재 서버 제품 이름만으로 두 독립 연산 backend 계열을 확인했다고 주장하지 않는다.
필수 엔진/아티팩트가 없는 사례는 `NOT_RUN` 또는 `BLOCKED_ENV`로 남기며 fixture로
대체해 완료 처리하지 않는다. 보존한 작은 P1a는 아래 §9이며 전체 P1 완료와 구분한다. 심핵·높은 권한의
집행·다중 하드웨어 설치와 독자 native 커널의 장기 목표는 각각 남아 있다.

<a id="structure-optimization-followup"></a>

## 8. 공식 구조 비교에 따른 내부 책임 분리 후속

같은 날 사용자는 온라인 유사 프로젝트를 조사해 구조를 최적화하도록 요청했다.
[비교·채택 기록](aios_architecture_comparison_20261008_ko.md)은 KServe/vLLM/llama.cpp/Ollama의
입구·엔진 책임, agiresearch/AIOS의 요청 관리, seL4/Genode의 권한·소유 경계를 공식 자료와
대조한 범위를 소유한다. 자료 참조는 `SOURCE_CURATION` / `RESEARCH`, 이번 내부
hosted 변경은 `SUPPORTING` / 개발 `PARTIAL`이다. upstream 코드 import는 0이며
기존 resource13 manifest와 native·KernelRoom 계약은 바꾸지 않는다.

`PreparedInference`와 `PreparedMessages`의 `validate_prepared()` 소비 계약을 대칭화하고,
`PendingInference`에서 legacy receipt 재구성 분기를 제거한다. legacy/messages의
명시적 admission 뒤 `RequestExecution._admit()`가 공통 lifetime을 초기화한다.
messages가 legacy 전용 인자6개에 `None`을 전달하던 경로를 제거하며 save-before-start,
cancel-save-before-signal, terminal once-only·failure poison을 유지한다.
instance validator shadow의 제어된 mock 재현은 Popen 시도1·실제 spawn0이었다.
[재현 원본](../../build/structure-optimization-20261008/validator-shadow-reproduction.json)을
보존하며 exact class allowlist 뒤 `type(prepared).validate_prepared(prepared)`와 class result
validator를 직접 호출하는 수정·양방향 shadow 부정 검증을 별도로 남긴다.
frozen/sealed object를 security capability로 설명하지 않는다.

public RPC·receipt3·schema·source 목록/count와 global active1·Task16·event64는 유지한다.
새 runtime source32의 bytes/hash는 달라지므로 §6의 P0 source/verdict·원본 실패 로그를
보존하고 `build/structure-optimization-20261008/`에서 새 manifest/artifact/verdict를
검증했다. 최종 narrow·새 전체 회귀와 source32 독립 판독은 **`PASS`**다.
[비교 기록 §6](aios_architecture_comparison_20261008_ko.md#6-후속-source와-검증-기록)이
최종 로그·source 범위와 결과를 소유한다. shadow 수정 전 narrow62와 첫 broad 실행은
interim이다. 성능 benchmark와 실제 모델·두 서버·stream·GPU·이미지·QEMU·실기기
검증은 `NOT_RUN`이다. P1/portable 후보와 round08 P2를 유지하며 이 조각 당시의 선택은
[보존한 전역 큐](../meta/minimal_io_and_maturity_workflow_ko.md#structure-optimization-current)를 따른다.

<a id="serve-p1a-current"></a>

## 9. 보존한 SERVE-P1a — 내부 Ollama chat와 HTTP fixture

### 9.1 채택 범위와 수명 경계

2026-10-09 사용자는 Cellivane 표시 이름과 서빙 고도화를 요청했다. 이름·영한 표기·
역할·온라인 조사 제한은 [제품 이름 정본](../meta/product_identity_and_naming_ko.md)이 소유한다.
이번 구현은 `SUPPORTING` hosted 조각으로 내부 explicit messages selector,
`hosted/linux/aios_engines/ollama_chat.py`의 어댑터·closed prepared·fixed bounded HTTP
worker, `RequestExecution.for_ollama(...)`의 공통 Task lifetime 연결에 한정한다.

검증 대상은 127.0.0.1의 HTTP fixture에 실제 request/response bytes를 보내고,
접수·저장·dispatch·완료·취소·poison 순서와 독립 증거 판독을 확인하는 경로다.
HTTP fixture는 실제 Ollama 설치나 모델 실행이 아니다. fixture의 PASS를 실제 서버
호환으로 표시하지 않으며 late result·worker 종료·engine 종료도 서로 구분한다.

지원 한도는 `attached` literal `127.0.0.1`·명시적 port·`POST /api/chat`이다. 입력은 plain
`system/user/assistant` roles의 messages1..16, 합계 UTF-8 content4096 bytes 이내이며
`stream=false`, `think=false`, `num_predict=64`를 고정한다. worker timeout30초·raw
response16KiB 이내의 completed `done=true/done_reason=stop` assistant text subset만
정상 결과로 수용한다. raw stats는 보존하고 normalized usage는 `None`이다.
`think=false`를 지원하지 않는 모델, length/tool/thinking·unknown response는 `UNKNOWN`으로
남기며 fallback·자동 재시도·thinking 제거 후 성공으로 축약하지 않는다. 이 범위는
[Ollama chat API](https://docs.ollama.com/api/chat)를 참고한 자체 서브셋이며 실제 서버 qualification은 아니다.

이 내부 공통 입구에는 canonical MAIN source/management/backend binding과 engine
stop 권한이 없다. attached 요청 취소를 whole-instance stop·model unload로 연결하지
않으며 single writer·legacy receipt3을 보존한다. active1·Task16·event64는 기존 **공개
daemon 경로의 제약**이다. 내부 P1a factory 자체가 모든 프로세스의 전역 active1을
보장한다는 의미가 아니며, 여러 factory를 병렬 호출하는 admission은 아직 검증하지 않았다.
공개 CLI/RPC의 엔진 선택 기능이나 실제 다중/병렬 엔진을 제공하는 변경이 아니다.

### 9.2 public family와 별도 P1a source closure

Ollama 모듈은 public legacy/fixture 실행에서 load하지 않는 **optional lazy dependency**다.
공개 source32에 실제 Ollama 지원이 들어 있다고 주장하지 않는다.

| 집합 | count·family | 의미 |
|---|---|---|
| 공개 legacy/fixture MAIN | source32; protocol6/run7 | 기존 실행 family 유지. P0/구조 후속 원본 hash와 새 source의 hash는 별개 |
| 공개 CLI / backend | CLI39·session11/0.11.0; backend19·protocol1/run2 | 공개 실행 family 유지. public engine selector나 attached stop 권한 추가 아님 |
| P1a 전용 closed entry | source33 = SERVE32 + `ollama_chat.py` | 새 HTTP fixture·독립 판독의 전용 bundle. public source32의 proof와 분리 |
| 전체 hosted Python / 추가 image candidate | 44; `CANDIDATE_P1A_IMAGE_SOURCES` | optional 모듈을 포함하는 별도 후보. 실제 image 생성·부팅·acceptance는 `NOT_RUN` |

producer·consumer·독립 verifier의 source 목록과 family 검사는 전용 bundle에 결속한다.
P0의 candidate43, source32/39/19와 구조 후속의 source32 snapshot·hash·PASS/FAIL은
보존한다. count가 같거나 기존 protocol family를 유지해도 이전 artifact를 새 bytes의
실행 proof로 승계하지 않는다.

### 9.3 현재 검증 기록

| 항목 | 상태 | 증거 범위 |
|---|---|---|
| P1a 최초 어댑터 회귀 | `PASS` | 31 tests·0 skip·4.919초. [최초 로그](../../build/cellivane-evolution-20261009/ollama-first.log) |
| 영향5 modules 회귀 | `PASS` | 77 tests·0 skip·6.836초. [영향 회귀 로그](../../build/cellivane-evolution-20261009/ollama-affected-regressions.log) |
| 독립 verifier 부정/경계 검사 | `PASS` | 28 tests·0 skip·0.789초. [verifier 로그](../../build/cellivane-evolution-20261009/ollama-verifier-regressions.log) |
| image candidate 검사 | `PASS` | 7 tests·0 skip·0.342초. [candidate 로그](../../build/cellivane-evolution-20261009/image-builder-first.log); 실제 image 실행 아님 |
| localhost HTTP fixture·Task raw artifact | `PASS` | 아래4개 Task의 실제 loopback transport/미시작/취소·late-unknown 경로. 실제 Ollama 모델 아님 |
| 전용 source33 독립 CLI 판독 | `PASS` | 4종 각 exit0·source_files_verified33. source/Task 증거의 판독이며 실제 서버·process liveness 판정 아님 |
| 전체 hosted 회귀 | `PASS` | Windows Python3.11.9·collected1122·executed/PASS1037·FAIL0·ERROR0·346.896초·exit0. 플랫폼·권한 조건으로85 skip(71 Linux/14 symlink). [최종 전체 로그](../../build/cellivane-evolution-20261009/full-hosted-final.log) |
| 실제 Ollama / managed llama.cpp | `NOT_RUN` | 설치·모델·서버 버전·compatibility qualification 없음 |
| 공개 CLI 선택·parallel·stream·shared memory | `PLANNED` / `NOT_RUN` | 이번 internal entry의 완료 조건 밖 |
| candidate44 이미지·QEMU·native·실기기 | `NOT_RUN` | source 목록 추가는 이미지나 native 실행 증거가 아님 |

독립 판독 결과는 다음과 같다. `PASS`는 fixture/증거 계약을 만족한다는 뜻이며
`UNKNOWN`을 성공 답변·엔진 취소 완료로 바꾸지 않는다.

| raw artifact | 독립 verdict | model_outcome·snapshot |
|---|---|---|
| [ollama-task.json](../../build/cellivane-evolution-20261009/final/ollama-task.json) | [PASS](../../build/cellivane-evolution-20261009/final/ollama-task-independent-verdict.json) | `ANSWERED`·3 |
| [ollama-not-started-task.json](../../build/cellivane-evolution-20261009/final/ollama-not-started-task.json) | [PASS](../../build/cellivane-evolution-20261009/final/ollama-not-started-task-independent-verdict.json) | `NOT_STARTED`·3 |
| [ollama-cancelled-task.json](../../build/cellivane-evolution-20261009/final/ollama-cancelled-task.json) | [PASS](../../build/cellivane-evolution-20261009/final/ollama-cancelled-task-independent-verdict.json) | `UNKNOWN`·4 |
| [ollama-unknown-late-cancel-task.json](../../build/cellivane-evolution-20261009/final/ollama-unknown-late-cancel-task.json) | [PASS](../../build/cellivane-evolution-20261009/final/ollama-unknown-late-cancel-task-independent-verdict.json) | `UNKNOWN`·4 |

네 verdict는 `artifact_family=ollama-adapter-fixture-v1`, `evidence_kind=protocol-contract`,
`source_files_verified=33`, `actual_server_qualification=false`,
`process_liveness_verified=false`다. [독립 CLI 원본](../../build/cellivane-evolution-20261009/final/ollama-independent-cli.json)은
명령·exit0·stdout을, [snapshot metadata](../../build/cellivane-evolution-20261009/final/snapshot-metadata.json)는
네 raw artifact와 manifest/verifier hash를 보존한다.
[source manifest](../../build/cellivane-evolution-20261009/final/source-manifest.json)의 SHA256은
`9250ad7e016dcad84b8c7ef3c3c9a84fe70010157b818bb09a5fb3f04e249586`이며
[runtime-source33](../../build/cellivane-evolution-20261009/final/runtime-source33)의 33파일과
live `hosted/linux/` 33파일이 해당 hash 목록에 모두 일치했다.

저장된 원본은 다음처럼 독립 재판독할 수 있다. 다른3개 raw artifact도 `--artifact`만
해당 파일로 바꿔 같은 manifest/source root를 사용한다.

```powershell
py -3 -B tools/hosted/verify_ollama_adapter.py --artifact build/cellivane-evolution-20261009/final/ollama-task.json --source-manifest build/cellivane-evolution-20261009/final/source-manifest.json --source-root build/cellivane-evolution-20261009/final/runtime-source33
```

최초 전체의 H1 binding-trace fixture는 Git dubious ownership 환경 오류를 만났다.
[first 전체 로그](../../build/cellivane-evolution-20261009/full-hosted-first.log)의
1122 tests·337.153초·FAIL3·ERROR17·85 skip과
[해당 fixture 원본](../../build/cellivane-evolution-20261009/trace-fixture-environment-first.log)의
37 tests·FAIL3·ERROR17을 보존한다. source 수정 없이 exact alias/resolved worktree의
trust를 runner 프로세스에만 추가했으며 global Git config를 변경하지 않았다.
[해당 fixture 재검사](../../build/cellivane-evolution-20261009/trace-fixture-environment-final.log)는
37 tests·0 skip·19.258초·PASS이고 최종 전체는 위 표의 terminal exit0로 확정했다.
[검증 결과 JSON](../../build/cellivane-evolution-20261009/final/validation-results.json)과
[전체 실행 metadata](../../build/cellivane-evolution-20261009/full-hosted-final.execution.json),
[fixture 실행 metadata](../../build/cellivane-evolution-20261009/trace-fixture-environment-final.execution.json)를 함께 보존한다.

31/77/28/7/37과 전체1122는 겹치는 검사 범위이므로 합산하지 않는다. 최종85 skip은
Linux 플랫폼 조건71개와 Windows symlink 권한 부족(WinError1314)14개다. Windows
callback/mock 검사와 실제 HTTP fixture는 Linux durable file/crash proof가 아니며
해당 Linux 실행은 `NOT_RUN`이다. P0/구조 후속의 원본 증거도 별도로 보존한다.
기존 CLI11 EvidenceReport/schema10 결합과 candidate43/44 운영 이미지 qualification의
미완료도 유지한다. 성숙도는 bounded `SUPPORTING`/`PARTIAL`이다.

### 9.4 후속 선택

다중·병렬·다층 엔진과 게임 shared-memory bridge의 책임·한도·관리/데이터 채널은
[Cellivane 엔진 조율 설계](cellivane_engine_orchestration_ko.md)의 bounded `PLANNED`
후보로 기록한다. 이 설계의 존재가 parallel 실행·native shared ring consumer나 새 ABI를
만들지는 않는다. actual Ollama와 managed llama.cpp의 별도 qualification, 공개 selector,
stream·resource admission은 후속 조각으로 고른다. portable 기본 운용·심핵·고권한과
native 장기 목표도 [전역 큐](../meta/minimal_io_and_maturity_workflow_ko.md#serve-p1a-current)에 유지한다.
