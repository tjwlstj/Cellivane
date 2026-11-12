# Cellivane 하드웨어 효율화 실험

상태: **PARTIAL / clean6·독립 matrix·29/8 선택·auto 900초 실제/독립 PASS, 로컬 Windows 회귀 815 PASS**.
기준일 2026-10-16. 이 문서는 기존 지속 시험의 증거에서 출발하는 새 runner와
하드웨어 profile 비교의 계약이다. 저장된 runner·cursor·policy를 읽어 아래 계약을
확인했다. [최종 공개 집계](benchmarks/2026-10-16-hardware-efficiency-summary.json)는
교차 비교·선택·최종 900초·회귀와 각각의 판정 범위를 보존한다. 새 revision CI는 별도다.
교차 비교에서의 선택과 최종 900초 실행을 구분하며, 아래 측정값을 다른
모델·호스트의 보편 성능 개선이나 CPU Runtime의 GPU 지원으로 확대하지 않는다.

## 출발 증거와 보존 범위

기존 [대형 모델 지속 시험](LARGE_MODEL_SOAK.md)과
[공개 집계](benchmarks/2026-10-16-large-model-soak-summary.json)는 변경하지 않는다.
집계 SHA-256은
`bc92e826895eef371028a64f101408776f741aa16d04736e1b85b8a11366cd7f`다.
원본 18-source snapshot, 두 최초 진단 실패와 최종 4B/8B 원문도 보존한다.
기존 681개 fixture PASS와 기록 재판독 PASS는 새 runner의 검증 결과가 아니다.

기존 8B run에서 service 첫/마지막 1분 완료 수는 107→83, HTTP wall p50은
0.3226963→0.2948355초, backend elapsed p50은 0.281→0.266초였다. 다음 요청 시작과
이전 완료 사이 간격 p50은 0.1776349→0.3485133초로 늘었다. 응답 latency 증가가
관측된 것이 아니므로 GPU 성능 저하·thermal throttling으로 설명하지 않는다.
매 완료 뒤 growing backend log 전체를 읽는 비용은 가능한 원인이지만 해당 함수의
소요 시간을 측정하지 않았으므로 인과관계는 미확정이다.

기존 14문제 반복의 8B 불일치 105개는 모두 같은 `list-count` 문제였다. 이 실패를
지우거나 답변을 수정해 성능·품질 개선을 만들지 않는다. 이번 비교도 고정 corpus의
기능·응답 일치와 측정된 비용을 확인하는 범위이며 일반 정확도 검증은 아니다.

## 소유권과 실행 경계

| 계층 | 이번 역할 | 상태와 경계 |
|---|---|---|
| 새 [runner](../tools/hosted/cellivane_seed_optimize.py) | 한 phase 실행, 설정·자원 관측, 계측과 증거 수집 | 구현 저장. 기존 soak runner를 수정하지 않고 별도 family로 사용 |
| 새 [log cursor](../tools/hosted/cellivane_log_cursor.py) | Bounded incremental log 관측과 byte/hash receipt | 구현 저장. 원본 보존·최종 전체 log 검사 유지 |
| 새 [profile/policy](../hosted/experimental/cellivane_seed/efficiency.py) | 고정 후보와 채택 규칙 | 순수 계산 구현. I/O·host 관측·실제 증거 인증·자동 탐색 없음 |
| [Public orchestration](../tools/hosted/cellivane_efficiency_lab.py) | 여섯 phase의 순차 ABC/CBA 실행과 manifest | Model 실행만 담당. Reader 재판독은 여섯 phase 뒤로 분리 |
| [Reader capture](../tools/hosted/cellivane_efficiency_capture.py) | 독립 reader의 binary stdout·stderr와 invocation sidecar 보존 | Model server를 기동하지 않음. Reader 실행·asset 검사는 model phase 뒤에 수행 |
| [Matrix collector](../tools/hosted/cellivane_efficiency_matrix.py) | 기존 여섯 summary·full-reader capture를 조인해 selection/receipt 생성 | Model·HTTP·subprocess 실행 없음. Source를 확인한 pure policy는 사용 |
| 기존 Seed·bridge·Ollama 경로 | Loopback admission, audit, 실제 tensor 실행과 정리 | Ollama가 tensor 계산·CPU/CUDA 배치를 담당. Cellivane이 tensor를 직접 이동하지 않음 |
| [독립 reader](../tools/hosted/verify_cellivane_efficiency.py) | Single run, 여섯 phase matrix, calibrated auto run의 별도 재판독 | 최종 기록 재판독 PASS. Producer·policy의 판정을 그대로 승계하지 않음 |

Runtime source family는 기존 18개와 새 3개를 연결한 21개다. Run schema 1의 family는
`cellivane-efficiency-run-v1`이며 private `efficiency-runs/<UUID>/soak.json`과 source snapshot을
연결한다. 독립 reader closure는 네 파일이며 orchestration·collector·capture helper는
runtime21과 별도 pipeline 도구다. 파일 수만 같다고 이전
source와 같은 것으로 취급하지 않는다. 새 증거는 기존 source·raw·aggregate 위에 쓰지 않는다.

Native C++ [Runtime/Murphy 0.1](RUNTIME_MURPHY.md)은 기존 고정 0.6B CPU 경로다.
[Murphy 0.2](MURPHY_SELECTION.md)의 calibration/choice 계약과 실제 `none` 결과도 유지한다.
이번 Ollama 실험으로 native worker의 GPU·큰 모델·MTP 지원을 추가했다고 쓰지 않는다.
Weight 값·quantization·repack, engine 간 KV 공유, native MTP, multi-GPU 실행은 범위 밖이다.

## 고정 모델과 비교 후보

모든 후보는 같은 공식 Qwen3-8B Q4_K_M GGUF를 사용한다. 정확한 artifact는
[UPSTREAM](UPSTREAM.md#immutable-official-qwen3-model-artifacts)의
5,027,783,488-byte 파일이며 SHA-256은
`d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`다.
Backend는 기존 pinned Ollama v0.40.2다. 임의 모델 대체·자동 target 축소·dependency
업데이트는 하지 않는다. 모델 metadata의 Apache-2.0과 engine·original code의 MIT는
각자의 범위이며 가중치·binary를 저장소에 포함하지 않는다.

| 후보 | 요청 GPU layer / total | CPU thread | 역할 |
|---|---:|---:|---|
| A — reference | 21 / 37 | 4 | 새 runner 안의 reference 설정 |
| B — GPU 후보 | 29 / 37 | 4 | A와 GPU layer 수만 다르게 비교 |
| C — thread 후보 | 29 / 37 | 8 | B와 CPU thread 수만 다르게 비교 |

공통 고정값은 context 2048, distinct slot 1, Seed completed cache 0, same-key waiter 0,
최대 output 128, temperature 0, think false, 비스트리밍 plain subset, KV f16,
Flash Attention auto다. 기존 baseline에서도 Flash Attention이 이미 활성화되어 있었으므로
이를 새 기능이나 이번 개선의 원인으로 부르지 않는다. `OLLAMA_KV_CACHE_TYPE=f16`을 명시하고
`OLLAMA_FLASH_ATTENTION` 환경변수를 제거해 backend auto 동작을 사용한다. Auto라는 요청만으로
실제 FA 상태를 확인했다고 쓰지 않는다. Backend-local prompt/KV reuse는
명시적으로 통제·관측한 범위만 기록하고 Seed cache 0과 동일시하지 않는다.

위 layer 수는 요청할 후보값이다. Fresh RAM/VRAM budget과 실제 CUDA log·loaded-model
관측이 모두 일치해야 실제 profile이 된다. GPU가 한 장 있다는 사실이나 `29/37` 계획만으로
실행·메모리 fit·residency를 확정하지 않는다. 새 `admission_forecast()`의 선언 budget은 다음과 같다.

- RAM required = 전체 model bytes + 7 GiB.
- VRAM forecast = 기존 21-layer `/api/ps.size_vram` 3,100,597,288 bytes +
  `ceil(max(0, layers−21) × model_bytes × 1.15 / 37)` + runtime allowance 256 MiB.
- Fresh free VRAM은 그 forecast + 1 GiB headroom 이상이어야 한다. Reference의 필요 free VRAM은
  4,442,774,568 bytes, 29-layer 후보는 5,692,926,138 bytes다.

이는 baseline model-size 관측에서 출발한 추정이며 layer별 allocation·KV가 균등하다는
증거가 아니다. 기존 soak의 별도 추정식을 바꾼 것이 아니다. Fresh preflight와 launch 직전에
같은 새 budget을 확인하고, 실패하면 layer를 자동 축소하지 않는다. 최소 RAM 3 GiB·free VRAM
768 MiB·온도 85°C guard, query 오류와 gap 경계도 유지한다. Preflight 뒤 다른 프로그램의
자원 사용이 바뀔 수 있고 budget은 OS resource reservation이나 fit proof가 아니다.

## 교차 실행과 계측 계약

예정 순서는 **ABC / CBA**, 두 round·총 여섯 phase다. 각 phase는 같은 14-case corpus를
네 번 반복해 완료 시 56개 scored 응답, 전체 완료 시 336개 scored 응답을 기록한다.
각 phase는 fresh owned Ollama server/create process를 사용하며 warmup 1개와 별도 bridge의
Seed 경유 1개를 scored 응답에서 분리한다. 전부 완료하면 profile당 scored 112개다.
Bridge는 같은 tensor worker의 Seed 경유·직접 Ollama 두 경로를 확인한다. 순서만 바꾼 단일
두-round 실험은 일반적인 성능 분포를 보장하지 않는다.

Public lab은 phase를 순차 실행하고 exit·producer acceptance·profile·56-row shape와
source/host/model/backend/corpus 불변을 확인한다. Phase 하나라도 실패하면 이어 진행하거나
자동 재시도하지 않는다. Reader·collector·regression·큰 asset hash 검증은 측정 phase와
동시에 돌리지 않고 여섯 model phase가 끝난 뒤 수행해 그 CPU/I/O 부하를 섞지 않는다.
Orchestration manifest의 순서는 local 실행 기록이며 trusted clock·host attestation은 아니다.

`calibrate` 비교는 **unpaced**, 최종 `soak`은 최소 시작 간격 **0.5초**다.
기존 0.5초 최소 시작 간격의 900초 결과와 새 unpaced 요청 수를 직접 나누어
새 log reader나 hardware profile의 가속 배수로 제시하지 않는다. 후보끼리는 같은 새
runner·계측·source·모델·corpus·sampling·출력 상한을 사용해야 한다.
기존 `wall_s` 의미를 바꾸지 않고 HTTP 완료와 그 뒤 producer 작업을 구분한다.

구현에 저장된 계측 항목은 다음과 같다. 지원 field의 존재와 실제 측정 결과는 구분한다.

- `started_s`·`completed_s`·`wall_s`와 raw backend의 대응 timing/token 정보.
- 응답 뒤 `receipt_started_s`·`receipt_completed_s`·`receipt_read_s`, phase의 `pacing_wait_s`,
  `log_started_s`·`log_completed_s`·`log_wall_s`·`log_poll_sequence`, `progress_write_s`, `post_complete_s`.
- 각 audit append의 시작/완료·wall을 연결하는 `audit_timings`, warmup·service·bridge·cleanup 구간.
- RAM/VRAM·온도 query 시간과 실제 sample 간격. Whole-host RAM, whole-device VRAM,
  backend loaded-model size를 서로 구분하며 per-process VRAM이나 연속 peak로 바꾸어 부르지 않음.

단계별 stopwatch가 없는 구간은 NOT_MEASURED로 남긴다. File hash는 OS page cache를
데울 수 있으므로 cold model/storage 성능을 주장하지 않는다. 비스트리밍 HTTP 완료 시간은
TTFT가 아니며 backend generation rate와 end-to-end 응답 처리율도 별개다.
`audit_timings`는 HTTP wall 안에 포함될 수 있어 모든 계측 구간을 더하면 중복 계산할 수
있다. 기록한 구간을 서로 완전히 배타적인 비용 분해로 취급하지 않는다.

## Log 관측의 안전 조건

Incremental 검사는 비용을 줄이는 후보이며 fatal coverage를 줄이는 기능이 아니다.
Cursor는 새 appended bytes와 bounded anchor만 읽고 strict UTF-8 decoding, 64-character scan
tail과 ordered per-line token state를 사용한다. 기본 log 16 MiB, line 64 KiB, read chunk
64 KiB, anchor 256 bytes 상한이다. `seq`·`[start,end)`·new bytes·chunk/prefix SHA·누적 logical
read/scan bytes·carry bytes·poll wall을 기록한다. Truncation·파일 identity 변경·관측한 anchor
변경·잘못된 encoding·과대 입력은 cursor를 실패 상태로 닫는다.

소유 writer 종료·output drain 뒤 `finish()`를 수행하고 최종 전체 raw log의 fatal/placement
검사를 유지한다. Anchor는 읽지 않은 과거 byte가 잠깐 변경됐다가 복원되는 경우를
인증하지 못한다. 독립 reader가 최종 raw log와 chunk/prefix receipt를 조인해야 하며
이 역시 hostile-process 또는 filesystem attestation이 아니다.

Unit/negative fixtures는 최소한 chunk를 가로지르는 fatal, 마지막 미완성 fatal,
잘못된 UTF-8, log 축소·교체, 크기 초과, 허용된 정상 log와 reference 검사와의
판정 동등성을 확인해야 한다. Raw bytes와 원본 hash를 보존한다. 이를 async audit,
fsync 생략, 원문 rotation/deletion이나 crash recovery 구현으로 확대하지 않는다.

저장된 cached-local log ABBA 비교는 8,203,944-byte 원문을 126개 append chunk로 재생했다.
Full guard의 wall은 39.7433/39.5516초, logical read는 각 523,756,153 bytes였고 incremental은
0.9370/0.7307초, 각 8,268,712 bytes였다. 두 방법은 같은 broad fatal vocabulary를 검사했다.
이 값은 guard read/scan 비용이며 writer 비용·physical disk I/O·실제 model throughput·
end-to-end 가속을 측정한 것이 아니다. 원문과 benchmark hash·receipts는 private evidence로 보존한다.

## 후보 채택과 실패 정책

동결된 `choose_profile()`은 각 후보를 reference와 비교하며 다음을 모두 요구한다.

- 두 round 각각과 전체에서 HTTP wall p50 ≤ reference × 0.95.
- 같은 비교 각각에서 14개 case의 `reference_case_p50 / candidate_case_p50` 중앙값 ≥ 1.05.
- 각 round·전체에서 어느 case의 p50도 reference 대비 10% 넘게 악화하지 않음.
- 전체 p95 ≤ reference × 1.05. 새 policy의 p95는 `(n−1)×0.95` 위치의 선형 보간이며
  이전 soak 집계의 nearest-rank와 구분함.
- 매 round의 각 case/repeat 출력 SHA 완전 일치, PASS outcome·resource guard, 같은
  model/backend/corpus/source 네 digest. 실제 host·실행 순서·원문 판정은 caller/독립 reader가 검사함.

통과 후보 중 전체 p50이 가장 작은 후보를 선택한다. 완전 동률이면 선언 순서상
`gpu29`가 `gpu29-threads8`보다 우선이다. Reference가 부적합하면 `eligible=false`이며
선택 record의 reference 이름이 실제 실행 허가나 성공 판정이 되지 않는다.
응답이 computed라는 이유만으로 parity나 정답을 PASS로 처리하지 않는다.

채택할 후보가 없으면 reference A를 유지한다. 더 많은 GPU layer나 CPU thread를 썼다는
이유로 후보를 고르지 않는다. 채택 후보는 별도의 최종 900초 지속 시험을 통과해야 하며
짧은 비교의 성공을 그 지속 시험의 PASS로 승격하지 않는다. 최종 지속 시험의 source·
설정·runtime counters·자원·판정·정리를 다시 연결한다.

기존 guard, deadline, max-token 거부, fatal 검사, request/audit/source joins, no-extra-dispatch와
owned cleanup을 보존하고 새 negative fixtures로 확인한다. 관측 누락·source 불일치·
미완료·guard·timeout·독립 FAIL을 느린 후보의 단순 성능 점수로 합치지 않는다.
실패 원문을 보존하며 재실행은 새 run/source identity로 구분한다.

## 현재 교차 비교와 선택

Clean ABC/CBA 여섯 phase는 각각 56개 corpus 응답을 완료했고 대응 full single-run
replay가 모두 PASS였다. Collector와 별도 matrix-only 판정도 PASS였으며
`efficiency-balanced-v1`은 `gpu29-threads8`을 선택했다. 총 scored 응답은 336개이고
각 phase의 exact-format은 52/56이다. 대응 case/repeat의 출력 SHA는 모든 후보에서
reference와 일치했다. 동일 응답은 정답이나 일반 품질 향상을 뜻하지 않는다.

| 고정 profile | Round 0 HTTP p50 (초) | Round 1 HTTP p50 (초) | 전체 HTTP p50 / p95 (초) |
|---|---:|---:|---:|
| reference — 21/4 | 0.45149950 | 0.44748320 | 0.45059105 / 1.209139905 |
| gpu29 — 29/4 | 0.29262620 | 0.30034105 | 0.29326795 / 0.705295040 |
| gpu29-threads8 — 29/8 | 0.28296045 | 0.28876300 | 0.28749135 / 0.717263380 |

선택 후보의 전체 p50/reference p50 비율은 0.63803165, case별 speedup ratio의 중앙값은
1.2585943이다. 두 값은 서로 다른 통계다. 두 후보 모두 reference 대비 gate를 통과했으며
선택은 전체 p50 최솟값 규칙을 따른다. 29/8이 29/4보다 다시 5% 개선해야 하는 규칙은
아니다. 두 round의 같은 모델·source·호스트·고정 corpus에 대한 관측이며 독립 문제
336개, 보편 speedup, 에너지 절감이나 모든 부하에서의 최적 설정으로 설명하지 않는다.
8-thread 사용 자체가 CPU 비용이나 전력 절감을 증명하지도 않는다.

이 선택의 최종 auto 900초 full replay·matrix linkage와 로컬 전체 회귀는 PASS이며
상세 증거·hash는 새 공개 집계에 기록했다.
짧은 교차 비교·matrix PASS가 그 뒤 실행의 PASS를 승계하지 않는다. 기존 18-source
지속 시험과 새 unpaced 비교 사이의 처리율을 직접 비교하지 않는 경계도 유지한다.

### 최종 auto 900초의 실제·독립 관측

선택된 `gpu29-threads8`의 별도 auto run은 producer `COMPLETED`·`acceptance=PASS`로
종료했고 최종 full-reader capture·matrix linkage도 PASS다. Run은
`f2d1d493-21d0-440e-84a0-c478cc46acdb`이며 exit 0·empty reader stderr를 확인했다.
아래는 원문 summary와 공개 집계의 관측이다. Producer의 source/model/backend 불변·cleanup
기록과 독립 reader의 판정 범위는 구분한다.

| 항목 | 최종 기록·재판독 범위 |
|---|---:|
| Admission / 기록 service | 900초 / 900.024672초 |
| Corpus computed | 1,768 |
| Exact-format / corpus 응답 | 1,642 / 1,768 |
| HTTP wall p50 / p95 | 0.2499207 / 0.4168895초 — p95 선형 보간 |
| 실제 CUDA layer / native CPU thread | 29/37 / 8 |
| Seed computed / backend calls | 1,770 / 1,770 — corpus + warmup 1 + bridge Seed 1 |
| `max_tokens=129` 거부 | 1개 |
| Cache hit / failure / timeout | 각각 0 |
| Audit record / timing | 5,314 / 5,314 |
| Active / inflight / waiter | 각각 0, closed |
| Service / 전체 resource sample | 289 / 299 |
| Service 최대 sample gap | 3.247519초 |
| Service 최소 host available RAM | 16,263,122,944 bytes — 약 15.15 GiB |
| Service 최소 device free VRAM | 1,524,629,504 bytes — 약 1.42 GiB |
| Service 최대 device used VRAM | 6,770,655,232 bytes |
| Service 최고 GPU 온도 | 49°C |
| 최종 log bytes / logical read / logical scan | 9,889,120 / 10,795,616 / 10,002,402 bytes |
| Log poll 수 | 1,771 |

소유 Job의 active process 0·cleanup confirmed와 두 port 닫힘, bridge 완료와 거부 전
추가 dispatch 없음까지 기록·재판독했다. Exact-format 불일치 126개는 모두 같은
`list-count` 문제의 반복이었다. 정상 완료와 정답을 구분하며 일반 품질 향상을 주장하지 않는다.
최종 reader의 `recorded-efficiency-single-run-integrity-and-bounded-log-work` PASS는
source21·현재 byte 비교와 기록 joins의 범위다. Resource 값은 whole-host RAM·whole-device
GPU의 sample이며 process 독점 메모리·연속 peak·메모리 누수 부재나 OS reservation 증거가 아니다.
Guard는 발동하지 않았지만 향후 OOM 방지나 다른 프로그램의 사용량을 보장하지 않는다.
Warmup·bridge는 위 corpus 수에 넣지 않는다. Window 뒤 완료 요청은 1개이며 service의
0.024672초 초과에는 진행 중 응답과 postresponse 작업이 포함돼 정확한 GPU drain 시간은 아니다.
이번 표의 요청 수를 기존 paced 18-source 시험이나
unpaced 교차 비교와 직접 나눈 가속 배수로 제시하지 않는다.

새 계측에서 scored 응답 뒤 receipt 재판독 합계는 약 0.7114초, log poll 구간 합계는
1.6258초, progress file 저장은 0.0741초였다. 최소 0.5초 pacing의 wait 합계는 406.3588초다.
HTTP wall에는 backend·audit 시간이 포함되므로 이 값들을 모두 더해 독립 원인별 합계로
제시하지 않는다. 이 paced 지속 시험도 backend의 최대 처리율·GPU 연속 포화 시험은 아니다.

최종 로컬 Windows model-free unittest는 **815 PASS / 0 skip / 250.306초**다.
CI나 실제 모델 실행의 증거와는 별도다. 초기 pilot 네 run은 원문과 source를 보존하고
최종 clean6·선택에서는 제외했다. 기존 지속 시험·Runtime 0.1·Murphy 0.2의 공개 집계와
동결 source는 이번 결과로 덮어쓰지 않는다.

## Auto 선택 자료와 실행

Selection file은 schema 1, family `cellivane-efficiency-selection-v1`이며 정확한 최상위
field는 `schema_version`, `family`, `host_profile`, `candidate_reports`다. `--profile auto`는
기본 `<storage-root>/selected-profile.json` 또는 명시한 `--calibration-file`을 읽고 pure policy를
재계산한다. Host의 logical CPU 수·RAM total·GPU index/name/driver/total과 새 source21·
backend/model/corpus identity가 현재 관측과 일치해야 하며 부적합 자료는 실행 전에 거부한다.

기본 file이 없으면 reference를 사용한다. 명시한 file의 누락·손상은 숨은 성공이나 자동
재측정으로 대체하지 않는다. Loader는 최대 256 KiB+1 bytes를 읽어 selection schema를 검사한다.
이 파일은 이전 결과를 연결하는 local 선택 자료이며 인증된 hardware 성능 보증이 아니다.
Runner가 raw 여섯 phase의 독립 replay를 자체 호출하는 것은 아니므로 별도 pipeline이 먼저
각 phase의 독립 PASS를 확인하고 candidate reports를 구성해야 한다. `calibrate` 호출 하나는
한 profile의 phase이며, public lab이 여섯 호출을 orchestration한다. Selection 자동 생성은
lab이 아니라 capture 결과를 확인하는 matrix collector의 역할이다.

### 1. Public ABC/CBA orchestration

다음은 Windows repo root에서 사용하는 실행 예다. 준비된 정확한 model/asset 경로를 입력하고
각 실패의 원문을 보존한다. 새 runner는 model을 다운로드하지 않으며 기존 검증된 Ollama lab
asset root를 사용한다. 이 lab 호출은 실제 모델을 여섯 phase에서 기동하며 적지 않은
시간·전력·저장을 사용한다. Phase별 subprocess deadline은 600초이며 failure/timeout은
해당 stdout과 orchestration 실패 상태로 보존한다.

```powershell
$taskEfficiencyAssets = Read-Host '기존 검증된 Ollama lab asset root의 절대경로'
$taskEfficiencyModel = Read-Host 'Qwen3-8B-Q4_K_M.gguf의 기존 local 절대경로'
$taskEfficiencyRoot = Join-Path $env:LOCALAPPDATA 'Cellivane/hardware-efficiency'
py -3 -B tools/hosted/cellivane_efficiency_lab.py --model-file $taskEfficiencyModel --asset-root $taskEfficiencyAssets --storage-root $taskEfficiencyRoot
if ($LASTEXITCODE -ne 0) { throw 'Calibration orchestration failed; preserve and review its evidence' }
```

Lab은 `calibration-matrices/<UUID>/orchestration.json`에 각 phase의 summary 경로·hash·
profile·순서·exit를 기록한다. `MODEL_RUNS_COMPLETED`는 여섯 producer 실행 완료이며
독립 PASS·선택 완료·최종 지속 시험 완료가 아니다. 마지막 stdout의 manifest 경로를 보존한다.

### 2. Phase별 full-reader capture

여섯 model phase가 모두 끝난 뒤 각 summary를 현재 source21과 full-reader closure4에
대조하는 single-run replay를 수행한다. Capture에는 raw stdout·stderr와 여덟 필드
sidecar가 필요하다: `argv`, `returncode`, `stdout_sha256`, `stderr_sha256`, `verifier_sha256`,
`summary_sha256_before`, `summary_sha256_after`, `verification_source_sha256`.
Exit 0·PASS·empty stderr와 summary 전후 hash·reader4 hash를 함께 확인한다.
Capture reader의 subprocess deadline은 600초다. Timeout이면 부분 binary stdout·stderr와
invocation을 보존하며 `returncode=null`, `timed_out=true`, `outcome=FAIL`이 된다.
Collector의 exit-zero gate를 만족하지 못하며 timeout 실패를 PASS로 재사용하지 않는다.

Capture helper는 각 summary의 parent 아래 새 `reader-capture-<UUID>/`에 `stdout.json`,
`stderr.txt`, `invocation.json`을 exclusive 생성하고 stdout으로 그 세 경로·`outcome`·
`stable_inputs`를 출력한다. PowerShell 기본 text redirection으로 원문 encoding을 바꾸거나
stdout verdict만 복사해서 sidecar를 충족한 것으로 취급하지 않는다. Full single-run
reader는 큰 model/backend asset도 검사하므로 이 절차는 model phase와 분리한다.
아래에서는 첫 단계가 출력한 manifest를 읽고 그 순서대로 여섯 capture를 모은다.

```powershell
$taskEfficiencyManifest = Read-Host 'MODEL_RUNS_COMPLETED를 기록한 orchestration.json의 절대경로'
$taskEfficiencyRepo = (Resolve-Path '.').Path
$taskEfficiencyOrchestration = Get-Content -Raw -LiteralPath $taskEfficiencyManifest | ConvertFrom-Json
if ($taskEfficiencyOrchestration.outcome -ne 'MODEL_RUNS_COMPLETED' -or @($taskEfficiencyOrchestration.phases).Count -ne 6) {
    throw 'Six completed model phases are required before reader capture'
}
$taskEfficiencyCaptures = @()
foreach ($taskEfficiencyPhase in @($taskEfficiencyOrchestration.phases | Sort-Object index)) {
    $taskEfficiencyCaptureText = py -3 -B tools/hosted/cellivane_efficiency_capture.py $taskEfficiencyPhase.summary.path --source-root $taskEfficiencyRepo
    if ($LASTEXITCODE -ne 0) { throw 'Phase replay/capture failed; preserve its files' }
    $taskEfficiencyCapture = $taskEfficiencyCaptureText | ConvertFrom-Json
    if ($taskEfficiencyCapture.outcome -ne 'PASS' -or -not $taskEfficiencyCapture.stable_inputs) {
        throw 'Phase capture did not pass with stable inputs'
    }
    $taskEfficiencyCaptures += [pscustomobject]@{
        summary = $taskEfficiencyPhase.summary.path
        verdict = $taskEfficiencyCapture.stdout
        invocation = $taskEfficiencyCapture.invocation
        stderr = $taskEfficiencyCapture.stderr
    }
}
```

### 3. Collector와 독립 matrix 판정

Collector는 `--summary`, `--verdict`, `--invocation`, `--stderr`를 각각 여섯 번 ABC/CBA
순서로 받고 `--source-root`, 새 `--output` selection file과 새 `--receipt` 경로를 요구한다.
중복 run, phase 순서·profile, source21 현재 byte와 snapshot, host/model/backend/corpus,
response/text와 capture/reader4 불일치를 거부한다. 출력 경로는 기존 file을 덮어쓰지 않으며
receipt를 먼저 쓰고 selection file을 마지막에 publish한다. 실패 시 남은 orphan receipt도
원본으로 보존한다. `COLLECTED`는 collector 완료이고 독립 matrix PASS와 구분한다.

Independent matrix 명령은 positional path를 selection file로 해석하는 `--matrix-only`와
`--matrix-receipt`를 사용한다. 여섯 원문의 semantic evidence·full-reader capture·policy
결정을 별도로 재계산하며 collector의 결론을 그대로 반환하지 않는다. 이 matrix 단계는
큰 model/backend asset을 다시 hash하지 않고 앞 단계 full capture를 조인한다. Input CLI
순서는 caller가 선언한 ABC/CBA이며 clock attestation이 아니고 hash도 인증 서명이 아니다.
아래는 capture 경로를 그대로 collector에 전달한다. Selection과 receipt는 새 고유 경로를
사용해 이전 자료를 덮어쓰지 않는다. 이 예시는 기본 `selected-profile.json`을 갱신하지 않고
다음 단계에서 생성된 selection 경로를 명시적으로 전달한다.

```powershell
$taskEfficiencySelection = Join-Path $taskEfficiencyRoot ('selected-profile-' + [guid]::NewGuid().ToString() + '.json')
$taskEfficiencyMatrixReceipt = Join-Path $taskEfficiencyRoot ('matrix-receipt-' + [guid]::NewGuid().ToString() + '.json')
$taskEfficiencyCollectorArgs = @('--source-root', $taskEfficiencyRepo, '--output', $taskEfficiencySelection, '--receipt', $taskEfficiencyMatrixReceipt)
foreach ($taskEfficiencyCapture in $taskEfficiencyCaptures) {
    $taskEfficiencyCollectorArgs += @('--summary', $taskEfficiencyCapture.summary, '--verdict', $taskEfficiencyCapture.verdict,
        '--invocation', $taskEfficiencyCapture.invocation, '--stderr', $taskEfficiencyCapture.stderr)
}
py -3 -B tools/hosted/cellivane_efficiency_matrix.py @taskEfficiencyCollectorArgs
if ($LASTEXITCODE -ne 0) { throw 'Matrix collection rejected its inputs; preserve evidence' }
py -3 -B tools/hosted/cellivane_efficiency_capture.py $taskEfficiencySelection --source-root $taskEfficiencyRepo --matrix-receipt $taskEfficiencyMatrixReceipt --matrix-only
if ($LASTEXITCODE -ne 0) { throw 'Independent matrix replay failed; do not start the auto soak' }
```

마지막 capture는 내부에서 `verify_cellivane_efficiency.py <selection> --source-root <root>
--matrix-receipt <receipt> --matrix-only`를 실행한다. `<...>` 표기는 인자 역할 설명이며
별도 실행 명령이 아니다. Capture가 PASS여도 실제 실행 순서·host의 적대적 위조에 대한
인증이 되지는 않는다. Collector·lab·capture 도구는 runtime21/reader4와 별도 source다.

### 4. Auto 900초와 최종 독립 판정

여섯 capture와 matrix의 독립 PASS를 확인한 selection file을 아래 최종 시험에 명시한다.
`--calibration-file`을 생략하면 기본 root의 `selected-profile.json`을 찾고, 그것도 없으면
auto는 reference를 고른다. 포트 기본값은 Seed
18991 / worker 18992이고 서로 다른 1024..65535 정수여야 한다. `--model`은 `8b-q4`,
`--repeat`는 4만 지원한다.

```powershell
py -3 -B tools/hosted/cellivane_seed_optimize.py --mode soak --profile auto --calibration-file $taskEfficiencySelection --model-file $taskEfficiencyModel --asset-root $taskEfficiencyAssets --storage-root $taskEfficiencyRoot --duration-seconds 900
if ($LASTEXITCODE -ne 0) { throw 'Final soak failed; preserve and review its evidence' }
```

Calibrated auto run의 최종 single-run reader에는 대응 `--matrix-receipt`도 필요하다.
독립 reader는 그 matrix와 실제 auto 설정·선택 artifact를 다시 연결하고 해당 run의
큰 asset을 새로 검사한다. Matrix PASS만으로 최종 900초 run을 PASS로 표시하지 않는다.
최종 run 뒤 출력된 summary를 사용한다.

```powershell
$taskEfficiencySoakSummary = Read-Host '최종 auto run이 출력한 soak.json의 절대경로'
py -3 -B tools/hosted/cellivane_efficiency_capture.py $taskEfficiencySoakSummary --source-root $taskEfficiencyRepo --matrix-receipt $taskEfficiencyMatrixReceipt
if ($LASTEXITCODE -ne 0) { throw 'Final auto-run replay failed; preserve evidence' }
```

Calibrate의 duration은 0, soak의 duration은 900만 지원한다. 실행 명령의 존재·fixture·
부분 phase 완료·independent PASS·최종 지속 시험·새 revision CI는 각각 별도 결과다.

## 현재 검증 상태

| 항목 | 상태 | 증거 범위 |
|---|---|---|
| Runner / cursor / profile-policy | 구현 저장 / PARTIAL | source21 계약·CLI·고정 상한 확인 |
| 초기 좁은 model-free fixture | Runner 6 / cursor 33 / policy 20 PASS | 해당 구현 단계의 fixture 이력이며 실제 model 성능과 별도 |
| 최종 전체 model-free 회귀 | 로컬 Windows 815 PASS / 0 skip / 250.306초 | Terminal unittest log hash를 공개 집계에 기록; CI·model 실행 아님 |
| Cached-log guard 비교 | 저장된 ABBA 측정 확인 | Guard wall/logical read scope만. Model·disk throughput 아님 |
| ABC/CBA 실제 비교 | Clean6 producer PASS | phase당 56개·총 336개, 대응 출력 SHA parity, exact-format 각 52/56 |
| 여섯 full replay / collector / 독립 matrix | PASS | source21·reader capture·원문 joins·동결 선택 규칙; live attestation 아님 |
| 교차 비교 선택 | gpu29-threads8 — 29/8 | 두 후보가 gate 통과, 전체 p50 최소 규칙. 최종 지속 시험 성공과 별도 |
| 최종 auto 900초 지속 시험 | 실제·독립 full replay / matrix linkage PASS | 1,768 corpus·1,642 exact-format, 1,770 Seed compute, source21·기록 joins·cleanup 범위. 전체 회귀/집계와 별도 |
| 새 공개 aggregate | 저장 / scope 명시 | 교차 비교·선택·최종 run·회귀·보존 이력과 source21/reader4/pipeline2 hash |
| 새 revision CI | 별도 확인 | 실제 publication revision의 terminal workflow |

Public 문서/집계에는 allowlisted 설정·hash·run ID·통계·판정 범위만 기록한다.
개인 절대경로·PID·원시 prompt/answer·환경 dump·원본 engine log는 private evidence에
보존한다. 기존 [개발 가이드](DEVELOPMENT_GUIDE.md)의 contract→budget→plan→관측→독립
verdict 순서와 [운영 가이드](OPERATIONS.md)의 세션·디스크·deadline 경계를 유지한다.
