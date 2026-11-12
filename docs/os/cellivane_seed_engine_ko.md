# Cellivane Seed 소형 모델 서빙 엔진

> 문서 역할: 격리된 Seed scheduler·HTTP 계약·실험 증거 정본
>
> 내용 검토: 2026-10-12 — v0.1.0 source13·실제 CPU smoke·기존 bridge 호환과 공식 Strata 고정 자료 대조
>
> 제품 관계: `SUPPORTING`. 개발 성숙도: `PARTIAL`. 실제 CPU smoke·cache/합류·bridge 호환·독립 재판독과 선택 experimental 회귀175개는 §6의 한정 범위에서 PASS다. 일반 성능·정확도 benchmark·native qualification과 구분한다.

**Cellivane Seed v0.1.0**은 작은 dense 모델을 위한 자체 서빙 프로그램이다.
직접 작성하는 부분은 제한된 계산 admission, 정확히 같은 요청의 완료 결과 cache,
진행 중인 동일 요청 합류와 HTTP 응답·감사 기록이다. 실제 token 계산은 외부의
pinned llamafile 0.10.5와 Qwen3-0.6B-Q8 CPU worker가 수행한다. 독립 tensor kernel,
모델 학습, native MTP, KV 공유나 답변 품질 향상을 구현한 것으로 해석하지 않는다.

제품 목적은 [제품 방향](../meta/aios_product_direction_ko.md), 현재 선택과 기존 설치·심핵
우선순위의 관계는 [전역 큐](../meta/minimal_io_and_maturity_workflow_ko.md#cellivane-seed-current)가 소유한다.
공개 Task 서빙은 [서빙 정본](aios_serving_design_ko.md), 기존 다중 엔진의 역할·원문 journal은
[브릿지 실험](cellivane_bridge_experiment_ko.md), 장기 병렬·다층·공유 메모리 방향은
[엔진 조율 설계](cellivane_engine_orchestration_ko.md)가 소유한다.
Seed는 `hosted/experimental`의 별도 프로그램이며 공개 Linux MAIN/Task admission,
관리 identity·stop 권한, native ABI나 운영 이미지 acceptance를 확대하지 않는다.

<a id="seed-current"></a>

## 1. 구현 책임과 실행 경계

| 위치 | 소유하는 책임 | 실행 증거의 경계 |
|---|---|---|
| [Seed core](../../hosted/experimental/cellivane_seed/core.py) | 요청 검증·identity key·LRU·한정 flight·동기 backend 호출·subscriber 결과 | 자체 scheduler이며 tensor 계산기나 executor가 아님 |
| [Seed HTTP server](../../hosted/experimental/cellivane_seed/server.py) | loopback HTTP subset·응답 검증·감사 기록·외부 backend transport | 기존 bridge adapter를 library로 사용; runtime에서 tools를 import하지 않음 |
| [Seed lab](../../tools/hosted/cellivane_seed_lab.py) | D: 자산 hash 대조·소유 CPU worker·smoke/serve·원문과 정리 관측 | Windows 실험 launcher; 운영 설치·endpoint PID binding 증거와 구분 |
| 기존 bridge `kind="openai"` | Seed의 OpenAI subset에 연결하는 기준·보조 역할 | 새 adapter kind 없이 실제 reference/candidate 시험 PASS; 범위·원문은 §6 |

현재 기본 profile은 한 CPU worker와 **서로 다른 계산 key 한 슬롯**을 사용한다.
대기 작업 queue나 token 단위 continuous batching은 없다. 같은 key의 subscriber 합류는
새 backend 호출을 만들지 않으며, 다른 key를 위한 여유 슬롯이 없으면 즉시 거절한다.
core 생성자의 configurable 상한은 기본 profile이나 실제 수락 결과가 아니다.
내부 public methods는 `SeedEngine.complete(payload)`의 검증·결과 수락,
`status()`의 잠금 아래 counter snapshot, `close()`의 새 admission 거절·cache 제거다.
별도 worker executor·background queue·공통 Task writer를 숨겨 두지 않는다.

## 2. 정확한 결과 cache와 동시 요청

| 항목 | v0.1.0 기본 계약 |
|---|---|
| distinct slots | `1`; 초과한 다른 key는 `BusyError`와 HTTP `429` |
| 동일 flight 합류 | 전체 대기 subscriber 최대 `8`; 계산 owner는 이 대기 수에 포함하지 않음; 초과는 `429` |
| 완료 cache | LRU 최대 `32`개·`1 MiB`; 정규화한 결과 JSON bytes와 ASCII key bytes의 합계 |
| 계산 identity | artifact/config identity와 정규화한 model·messages·max_tokens·temperature 0·stream false를 hash |
| cache 수락 | 검증된 단일 assistant text·`finish_reason="stop"`·정수 usage를 가진 완료 결과만 저장 |
| 실패 | backend 오류·미완료·지원하지 않는 응답은 저장하지 않음; 감사 저장 실패는 poison/closed로 거절 |
| 실행 한도 | 기본 backend/joiner 한도 `90초`; backend I/O는 transport가 별도로 한도를 집행 |

model·messages의 순서·role·content·공백과 token budget이 달라지면 같은 요청으로
취급하지 않는다. lab의 identity는 binary·model hash와 실행 설정에 결속한다.
일반 server의 `--identity`는 운영자가 제공하는 격리 key이며 그 문자열 자체가
실제 binary/model 검증이나 인증을 수행하지 않는다. artifact나 실행 설정을 바꾸면
identity도 바꾸고 새 source·실행 기록을 보존해야 한다.

완료 cache hit은 **이전에 수락한 결과를 재생**한다. temperature 0이라는 이유만으로
새 token 계산이 매번 bit 단위로 같거나 같은 품질이라고 주장하지 않는다.
응답의 `usage`는 원래 완료 결과에 대한 논리적 token 수다. cache hit·합류 subscriber의
usage를 새 backend 계산량으로 합산하지 않는다. `computed`·`cache_hits`·`coalesced`와
`backend_calls`를 별도 관측한다. §6은 세 cache miss/hit의 관측이며 일반 token 성능·비용 개선을 증명하지 않는다.
llamafile의 알려진 optional `prompt_tokens_details.cached_tokens`는 정수 범위를 검증하고
정규화한 세 token 합계와 분리한다. upstream의 이 값을 Seed cache hit 횟수로 해석하지 않는다.

core cache는 process 내부의 임시 상태이며 eviction·close 때 제거한다. 이는 Python
allocator·모델 가중치·backend KV까지 `1 MiB`로 제한한다는 뜻이 아니다. 민감한 요청·
응답이 cache에 남을 수 있고, server의 `backend_exchange` 감사 파일에는 원문이 저장된다.
cache 비지속성과 감사 원문의 지속성을 구별하고 D: 실험 폴더를 사용자 데이터로 다룬다.

## 3. HTTP subset과 취소 의미

| 입구 | 현재 의미 |
|---|---|
| `GET /health` | admission layer가 closed/poisoned인지 확인; `scope="serving-admission-only"` |
| `GET /v1/models` | 설정된 단일 model 표시; 모델이 실제 계산 가능하다는 단독 증거가 아님 |
| `GET /v1/status` | scheduler counter·identity·한도·감사 폴더와 외부 tensor backend 경계 |
| `POST /v1/chat/completions` | 완료형 단일 assistant text subset; stream·tool·thinking 미지원 |

server는 literal `127.0.0.1`에만 bind하며 정확한 Host와 Origin 부재를 요구한다.
JSON HTTP body는 `1..32768 bytes`, 정규화한 inference JSON은 최대 `16384 bytes`다.
plain `system/user/assistant` messages는 `1..32`개이고 user role을 최소 하나 포함해야 한다. `max_tokens`는 `1..512`이며 기본 `128`이다.
temperature는 유한한 숫자 `0`, stream은 `false`만 허용한다. 알 수 없는 request field,
잘못된 model·role·usage·다중 choice·미완료 finish·thinking/tool 응답은 거절한다.
backend raw response와 Seed 전체 응답 envelope는 각각 최대 `256 KiB`로 검사한다.
HTTP 연결은 최대 `12`, 초과 연결은 `503`; scheduler의
계산 초과 `429`와 구분한다. keep-alive·browser API·cloud route·인증 서비스는 범위 밖이다.

연결 종료나 joiner timeout은 **그 subscriber의 결과 대기**에 관한 사건이다.
다른 subscriber가 공유하는 계산을 강제로 중단하거나 backend process·모델·KV를
해제하는 권한이 아니다. 현재 독립 cancel endpoint나 native cancellation은 없다.
Python 동기 backend callable을 강제 interrupt하지 않으며, owner의 늦은 결과는
deadline 실패로 처리한다. close도 진행 중 backend의 즉시 중단을 증명하지 않는다.

감사 기록은 한 writer가 순번·이전 hash를 연결하고 각 파일을 exclusive create·flush·
fsync한다. 최대 `10000` records·`64 MiB`를 넘거나 저장에 실패하면 새 결과를 거절한다.
이는 원문 무결성·실행 관측을 위한 구조이며 authentication·Windows directory fsync·
전원 차단 복구나 endpoint PID binding의 proof가 아니다.

## 4. Strata에서 참고한 것과 채택하지 않은 것

조사일은 **2026-10-12**다. 기존 브릿지의 고정 조사·작은 모델 header 검사 자료는
v0.1.41 commit `fb58e0dbc8399662c0e47c76578c6e878b14f6cf`에 묶인 역사 증거다.
이번 공식 최신 release는 [v0.1.43](https://github.com/Niko1221/Strata/releases/tag/v0.1.43),
고정 source commit은 `7695859aa13afb248bdb4d36f9b2e95707db079d`다.
최신 기능을 과거 inspector 실행 결과에 소급하지 않는다.

| 공식 source에서 확인한 사실 | Seed의 독립 설계 결정 |
|---|---|
| [모델 geometry](https://github.com/Niko1221/Strata/blob/7695859aa13afb248bdb4d36f9b2e95707db079d/include/strata/core/layout.hpp)는 48-layer hybrid attention·512 expert MoE와 tensor shape를 검증한다. [inspector](https://github.com/Niko1221/Strata/blob/7695859aa13afb248bdb4d36f9b2e95707db079d/tools/strata_inspect.py)는 `qwen4exp`를 요구하고, [packer](https://github.com/Niko1221/Strata/blob/7695859aa13afb248bdb4d36f9b2e95707db079d/tools/iq_pack.py)는 expert tensors를 요구한다. | tiny dense Qwen3를 Strata kernel 설정만 바꿔 실행할 수 있다고 보지 않는다. 작은 모델의 token 계산은 별도 llamafile backend에 맡긴다. |
| [서버 source](https://github.com/Niko1221/Strata/blob/7695859aa13afb248bdb4d36f9b2e95707db079d/serve/server.py)는 HTTP·service·resident engine 책임을 나누며 `--engine` 기본값은 `mock`이다. | HTTP 생존과 실제 모델 qualification을 구분한다. Seed의 health와 bridge의 Strata UNKNOWN 차단을 실추론 proof로 바꾸지 않는다. |
| [batching 설명](https://github.com/Niko1221/Strata/blob/7695859aa13afb248bdb4d36f9b2e95707db079d/docs/BATCHING.md)은 별도 slot의 decode를 함께 실행하고 slot별 모델 상태를 가진다. | Seed의 같은 key 합류는 한 번의 완료 결과를 여러 subscriber에 전달하는 scheduling이다. token batching·공유 KV와 구분한다. |
| [DETAILS](https://github.com/Niko1221/Strata/blob/7695859aa13afb248bdb4d36f9b2e95707db079d/docs/DETAILS.md)는 optional `--mtp`와 비-MTP draft/단일 token 경로, temperature 0에서도 계산 경로에 따른 수치 차이를 설명한다. | MTP·draft head·target verification을 구현하지 않는다. 정확한 cache replay와 새로운 계산의 결정성을 구별한다. |

공식 [README](https://github.com/Niko1221/Strata/blob/7695859aa13afb248bdb4d36f9b2e95707db079d/README.md)의
권장 GPU 요구와 기존 pin의 INSTALL에 있는 8GB slow 안내는 별도 문구다. 8GB라는
이유만으로 절대 실행 불가라고 단정하지 않는다. 현재 tiny 모델 적용의 핵심 제약은
지원 architecture·모델 전용 tensor 경로다. 실제 Strata 추론은 이번 Seed 작업의 수락 대상이 아니다.

고정 [Strata LICENSE](https://github.com/Niko1221/Strata/blob/7695859aa13afb248bdb4d36f9b2e95707db079d/LICENSE)의
MIT 표시는 직접 확인했지만 종속 코드·모델의 개별 사용 조건을 대신하지 않는다.
이번 채택은 source-only 아이디어 참고와 독립 작성이며 upstream 원문·코드를 복사하지 않는다.
기존 Linux resource manifest의 `schema1/resources13/code_import0` 정책과 공개 source family를 유지한다.

## 5. 로컬 실행과 브릿지 호환 시험

lab의 기본 결과 root는 `D:/AIOS/cellivane-seed-20261012`다. 기존 bridge의 자산 root
`D:/AIOS/cellivane-bridge-20261009`에서 pinned binary·동일 Qwen GGUF를 재사용하되
새 source hash·설정·원문·counter·소유 수명을 새 run에 기록한다. 기존 bridge의 PASS,
launcher hash·정리 결과를 새 Seed source의 실행 증거로 승계하지 않는다.

D:에서 바로 사용하는 [Run-Seed-Smoke.cmd](D:/AIOS/cellivane-seed-20261012/Run-Seed-Smoke.cmd)는
시험 후 정리하며, [Run-Seed-Server.cmd](D:/AIOS/cellivane-seed-20261012/Run-Seed-Server.cmd)는
명시적으로 서비스를 기동한다. 사용 범위와 API는 [START-HERE.txt](D:/AIOS/cellivane-seed-20261012/START-HERE.txt)에 기록했다.
이 입구는 아래 최종 local source snapshot을 사용하며 설치 패키지나 Git release가 아니다.

저장소 root에서 사용하는 입구는 다음과 같다. 이 명령의 실제 실행 결과는 §6에 따른다.

```powershell
py -3 -B tools/hosted/cellivane_seed_lab.py --mode smoke
py -3 -B tools/hosted/cellivane_seed_lab.py --mode serve
```

`smoke`는 cold/warm 요청·동일 flight 합류·다른 key 과부하와 기존 bridge의
`kind="openai"` 연결을 검증하도록 준비한다. `serve`는 사용자가 명시적으로 기동하는
로컬 실험 서비스다. 기본 Seed port는 `18941`, CPU worker는 `18942`이며 smoke는
Ollama 비교 worker `18932`도 사용한다. 빈 port 사전 확인과 소유 Job 관측은 endpoint
PID의 결속과 다르다. 실제 source와 실행 전후 port·process 정리 관측을 함께 보존한다.

## 6. 현재 검증 기록

실제 PASS run은 [c9e6ccf2의 lab summary](D:/AIOS/cellivane-seed-20261012/lab-runs/c9e6ccf2-85a1-465f-b2ff-c169375974a4/lab-summary.json)다.
실행 source closure는 Seed 4개·기존 bridge 7개·lab 2개의 총 **13개**이며 실행 중
불변이고 현재 runtime13 hash와도 일치한다. 최종 verifier 변경은 이 실행 source에
포함된 것으로 소급하지 않는다. 실제 실행의 snapshot `seed-0.1.0-a8b63945929d` 이후
독립 verifier를 보강했으며 runtime·launcher13은 변경하지 않았다.
최종 [source manifest](D:/AIOS/cellivane-seed-20261012/program/seed-0.1.0-160d7d4d9082/source-manifest.json)는
16파일을 묶고 `package_sha256=160d7d4d90820311e7968517fceb26a71cfa87f70e959d69220eda19c67a4b00`이다.
이는 manifest에 기록한 package identity이며 actual source13과 최종 검사/verifier 범위를 구분한다.

| 항목 | 현재 상태 | 확인한 범위·원문 |
|---|---|---|
| 선택 experimental 최종 회귀 | `175 PASS`·0 skip·9.375초 | [최종 stable 로그](D:/AIOS/cellivane-seed-20261012/development/final-stable-regressions-b0132ead-4d10-4ed1-8541-d10a15641234.log); bridge99·Seed core20·HTTP19·lab9·verifier28. 전체 hosted/native 실행으로 확대하지 않음 |
| pinned 작은 모델 CPU cache miss/hit | `PASS` | 세 요청 모두 첫 완료와 동일 결과 cache 응답; 실제 답변 품질은 아래 표와 별도 |
| 동일 flight 합류·다른 key 초과 | `PASS` | 실제 동시 두 응답 `computed`/`coalesced`, backend 호출 증가 1, 다른 key HTTP `429` |
| 기존 bridge 실제 호환 | `PASS` | Seed reference+Ollama 0.40.2 candidate가 `COMPLETE`·2 `ANSWERED`; [8-record journal](D:/AIOS/cellivane-seed-20261012/runs/450c6a91-b854-426d-8ba8-a17a0fa851bb/0008-final.json) 독립 재판독 PASS |
| scheduler 감사 | `PASS` | [75a88a9d 감사](D:/AIOS/cellivane-seed-20261012/seed-runs/75a88a9d-945c-4fdd-a05e-7b3aae8861fd/000024.json), 전체24 records·scheduler17; computed/backend_calls5·cache_hits3·coalesced1·rejected1·failures0 |
| 소유 Job·종료·port 관측 | `PASS` | 3개 모두 suspended create→Job assign→resume·thread/process handle closed·Job active0·cleanup confirmed; ports18932/18941/18942 closed; shutdown closed, active/inflight/waiters0 |
| 독립 Seed/bridge 재판독·최종 source package | `PASS` | 실제 원문의 Seed 감사와 bridge8-record journal을 독립 판독; 최종16파일 manifest와 실행13파일의 일치. verifier 강화 후에도 runtime·launcher 불변 |
| 일반 성능·메모리·품질 비교·새 계산의 결정성 | `NOT_RUN` | 아래 cache 재생 관측을 일반 token 계산 성능·정확도 benchmark로 확대하지 않음 |

아래 시간은 이미 로드된 CPU worker의 **완료 결과 cache miss 첫 생성**과 같은 process의
정확한 입력 cache hit을 `perf_counter`로 잰 값이다. 모델 cold load는 제외한다.
각 miss/hit은 한 번씩의 관측이며 품질 질문도 세 예시뿐이다.

| 예시 | cache miss / hit | 실제 출력 | 예상·판정 |
|---|---|---|---|
| 산술 | 436.795 / 5.583 ms | `7 + 8 = 15` | 예상 `15`; 정답 숫자는 있으나 only-number 형식 실패 |
| 제어 문자열 | 261.648 / 5.791 ms | `CELLIVANE_OK` | exact 성공 |
| 한국어 수도 | 333.094 / 5.188 ms | `대한민국` | 예상 `서울`; 사실 질문 오답 |

세 예시의 exact 성공은 **1/3**이다. fallback이나 출력 교정은 없고 cache는 오답도
같이 재생한다. 품질 향상은 관측하지 않았으며 이 표는 일반 정확도 benchmark가 아니다.
실제 CPU 배치는 [Seed worker 로그](D:/AIOS/cellivane-seed-20261012/lab-runs/c9e6ccf2-85a1-465f-b2ff-c169375974a4/seed-worker.log)와
[Ollama CPU 로그](D:/AIOS/cellivane-seed-20261012/lab-runs/c9e6ccf2-85a1-465f-b2ff-c169375974a4/ollama-candidate.log)에 묶인다.
Job 정리 관측도 backend stop API·KV release·endpoint PID binding·독립 OS liveness의 proof는 아니다.

최초 [7dc63f83 run](D:/AIOS/cellivane-seed-20261012/lab-runs/7dc63f83-b95f-494c-a561-c2a2a0010fb6/lab-summary.json)은
llamafile의 알려진 optional `usage.prompt_tokens_details`를 거절했다. 원본의
`outcome="COMPLETED"` 오표시와 failures9·독립 verifier FAIL을 보존한다. usage 검증·
정규화와 smoke 수락을 수정한 뒤 위 별도 run을 실행했으며 원본 실패를 덮지 않았다.
중간 [48개/0.903초](D:/AIOS/cellivane-seed-20261012/development/regression-a1369a02-a8f6-4011-903f-fb7d7729d499.log)와
[173개/10.227초](D:/AIOS/cellivane-seed-20261012/development/final-regressions-e7d020fc-df1d-45bc-b22a-d2e646cf50cf.log)
로그도 보존하며 위175개 최종 회귀와 구분한다. 종합 provenance는
[최종 감사 파일](D:/AIOS/cellivane-seed-20261012/development/final-audit.json)에 연결한다.

저장된 실제 원문을 재판독하는 입구는 다음과 같다. 이는 모델을 다시 실행하지 않는
검증 명령이며 verdict의 `actual_backend_qualification`·`process_liveness_verified`는
`false`다. 원문과 기록의 결속을 확인하는 판정과 실제 engine/OS qualification을 구분한다.

```powershell
py -3 -B tools/hosted/verify_cellivane_seed.py D:/AIOS/cellivane-seed-20261012/lab-runs/c9e6ccf2-85a1-465f-b2ff-c169375974a4/lab-summary.json
py -3 -B tools/hosted/verify_cellivane_bridge.py --run-directory D:/AIOS/cellivane-seed-20261012/runs/450c6a91-b854-426d-8ba8-a17a0fa851bb
```

기존 브릿지·P1a·P0의 결과는 각 정본과 해당 source에 보존한다. 공개 Linux 이미지,
native binding·관리 권한·공유 메모리·GPU/MTP/KV·독립 tensor kernel은 이번 실험이나
fixture PASS로 승격하지 않는다. 후속 source가 바뀌면 새 snapshot과 결과를 분리한다.

## 후속 독립 공개 베타 (2026-10-12)

위 0.1.0 snapshot 이후의 모델 크기·CPU/CUDA 배치 비교와 공개 저장소는
[독립 공개 베타 정본](cellivane_seed_public_beta_ko.md)에 별도 기록한다. 새 작업은
`D:/AIOS/cellivane-seed-public` 및 공개 `tjwlstj/cellivane-seed`의 `beta`에 있으며,
원래 AIOS native/public Linux acceptance나 위 역사 bundle을 소급 승격하지 않는다.
