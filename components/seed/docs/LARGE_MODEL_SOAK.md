# 대형 모델 CPU·CUDA 지속 시험

상태: **PARTIAL / 최종 source 4B smoke·8B 지속 실행 실제·독립 PASS, 로컬 회귀 681 PASS**.
검토일 2026-10-16. 이 문서는 고정 Ollama backend와 Seed·bridge를 사용한 별도 자원·
지속 실행 시험의 계약과 [최종 공개 집계](benchmarks/2026-10-16-large-model-soak-summary.json)를 설명한다.
아래 선언 한도와 실제 관측을 구분한다. 지속 실행 PASS는 일반 품질·안정된 처리량·
속도 향상이나 CPU 한정 Runtime/Murphy의 GPU 지원을 뜻하지 않는다. 새 revision CI는 별도다.

## 목적과 기존 경계

먼저 4B Q8_0의 짧은 smoke로 새 CUDA 실행 경로와 관측을 확인한 뒤, 8B Q4_K_M을
부분 CUDA offload로 900초 admission window에서 실행한다. 모델의 정상 완료·실패와
latency, CPU RAM·VRAM·온도를 함께 관측하는 기능·자원 시험이다. 장치가 존재하거나
계획한 layer 수가 양수라는 이유로 실제 offload나 지속 실행을 PASS로 쓰지 않는다.

Tensor 계산은 pinned **Ollama v0.40.2**가 수행한다. Cellivane은 요청 admission,
고정 설정·모델 identity, 소유 프로세스, 관측·guard·정리와 증거를 담당한다.
[Runtime/Murphy 0.1](RUNTIME_MURPHY.md)의 소유 C++ worker와
[Murphy 0.2](MURPHY_SELECTION.md)의 선택 controller는 기존 CPU 한정 범위를 유지한다.
이번 시험으로 그 worker가 큰 모델·GPU를 지원하거나 Murphy가 가속된다고 승격하지 않는다.

기존 [모델·배치 비교](BENCHMARKS.md), 0.1·0.2의 source·raw·공개 aggregate는 보존한다.
새 시험의 source closure와 모델·binary·config·관측·결과를 별도로 묶는다. 과거 snapshot의
4B partial CUDA PASS는 출발점이며 새 source의 실행 증거를 대신하지 않는다.

## 고정 artifact와 라이선스

| 역할 | Artifact | Bytes | SHA-256 |
|---|---|---:|---|
| 초기 smoke | Qwen3-4B-Q8_0.gguf | 4,280,404,704 | `8c2f07f26af9747e41988551106f149b03eb9b5cb6df636027b6bf6278473300` |
| 지속 시험 | Qwen3-8B-Q4_K_M.gguf | 5,027,783,488 | `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |

공식 immutable URL·model-card metadata·engine pin은
[UPSTREAM](UPSTREAM.md#immutable-official-qwen3-model-artifacts)을 따른다. Local cache의
존재·파일 크기와 실행 직전의 전체 byte/hash 일치를 구분한다. 원본 model 값·quantization·
파일을 변경하지 않는다. 모델 metadata는 Apache-2.0, Ollama와 Cellivane original code는
각각 MIT이며 외부 binary의 전이 구성요소·notice는 별도 경계다.

4B Q8과 8B Q4는 parameter 수와 quantization이 동시에 다르다. 작은 고정 입력에서
답변이 달라도 이를 모델 크기만의 효과나 Cellivane의 품질 개선으로 설명하지 않는다.
8B Q4 파일 크기가 VRAM보다 작아 보여도 KV·workspace·backend overhead를 포함한 full
GPU residency를 보장하지 않는다.

## 실행 계약

| 항목 | 승인된 초기 범위 |
|---|---|
| Backend / 장치 | 기존 고정 Ollama v0.40.2, NVIDIA CUDA 한 장, Vulkan 비활성화 |
| Model·요청 | 위 고정 GGUF, context 2048, CPU thread 4, distinct compute slot 1, completed-result cache 0, same-key waiter 0 |
| 생성 | 최대 128 token, temperature 0, think false, 비스트리밍 plain 완료 subset |
| 입력 | 기존 비교의 short 12개와 medium 2개의 고정 14-case corpus 순환; corpus·prompt/config hash 연결 |
| 준비 / warmup | `warmup.wall_s` 측정, backend `load_duration`은 존재할 때 raw field로 보존. 전체 prepare/hash·독립 load stopwatch는 NOT_MEASURED. Warmup은 window·최소 수에서 제외 |
| 지속 구간 | Warmup 이후 admission window 900초. 마지막 admitted request에는 최대 120초 drain 범위를 별도 기록 |
| 별도 bridge 확인 | Service/drain 뒤 전체 deadline 180초. 각 backend 요청 deadline 120초 및 service drain 120초와 구분 |
| 관측 | 3초 wait 기반 RAM·VRAM·온도 sampling. 실제 sample 간격·query 시간·누락을 기록하고 gap 10초 초과를 거부 |
| 자원 guard | 가용 RAM < 3 GiB 또는 가용 VRAM < 768 MiB 또는 GPU 온도 ≥ 85°C면 guard. 필수 probe 실패도 guard로 처리 |
| 최소 완료 | Smoke는 corpus computed 4개, soak는 24개 이상. Warmup·bridge·거부·실패를 최소 수에 합치지 않음 |
| 추가 상한 | 요청 시작 간격 최소 0.5초, corpus 요청 최대 2048개, backend log 16 MiB, telemetry 8 MiB, sample gap 최대 10초 |
| 실패 | 원문·부분 결과 보존. 자동 재시도·대체 답변·자동 모델 교체로 실패를 숨기지 않음 |

900초는 계속 GPU kernel이 실행되는 시간을 뜻하지 않는다. HTTP·계산·관측·동기 증거
쓰기와 다음 admission 사이의 간격이 포함될 수 있다. 전체 CLI 시간은 준비·warmup·
900초 window·마지막 요청 drain·별도 bridge 확인·정리 때문에 더 길 수 있다. Window 종료 뒤 새 요청을
받지 않는 것과 이미 시작한 계산을 취소하는 것은 다르다. Generic callable이나 blocked
OS filesystem I/O를 중단하는 hard wall-time 보장은 제공하지 않는다.
Guard는 새 admission을 닫으며, 이미 진행 중인 요청을 즉시 취소했다는 뜻은 아니다.
진행 중 요청은 최대 120초의 request/drain 범위에서 끝난 뒤 실패·정리 상태를 기록한다.
그 범위를 넘은 결과는 acceptance를 통과하지 못하며 모든 OS I/O의 강제 중단을 보장하지 않는다.

## RAM·VRAM 계획과 실제 관측

실행 전 fresh snapshot으로 다음 선언 budget을 확인하는 계획이다.

- RAM: **전체 model file bytes + host 2 GiB + workspace 1 GiB + headroom 4 GiB**.
- VRAM: fresh available VRAM에서 **headroom 1.5 GiB + workspace 0.75 GiB**를 남기고,
  model/layer byte 추정에 **1.15 계수**를 적용해 요청할 offload layer 수를 정수로 고른다.

현재 고정 total layer 수는 **4B 37개, 8B 37개**다. 8B의 고정 GGUF metadata에서
`qwen3.block_count=36`이며 실제 backend의 output layer 포함 offload total은 37이었다.
[공식 Qwen3-8B config](https://huggingface.co/Qwen/Qwen3-8B/raw/main/config.json)의
`num_hidden_layers=36`도 이를 뒷받침한다(2026-10-16 확인). 이 moving main 문서는 보조
근거이며 정확한 model pin의 GGUF metadata·native offload 원문을 대체하지 않는다. Layer당 추정은
`model_bytes / total_layers × 1.15`이며 남은 VRAM을 이 값으로 나눈 몫과
`total_layers - 1` 중 작은 값을 사용한다. 1개 미만이면 dispatch 전에 거부한다.
처음 probe와 backend launch 직전 probe에서 budget을 각각 확인하며, 저장 디스크의
free bytes도 `2 × model_bytes + 5 GiB` 이상을 요구한다. 이는 누적 로그의 자동 disk quota가 아니다.

이 계산은 file bytes에 기초한 admission 추정이다. 실제 tensor 배치·KV allocation·
allocator 예약·OS RAM/VRAM quota를 집행하거나 모든 model page의 residency를 증명하지
않는다. 다른 프로그램의 자원 사용은 preflight 뒤에도 바뀔 수 있다. 계획한 layer 수,
backend가 실제 offload한 `n/total`, model/KV/compute buffer, `/api/ps.size_vram`과
device 전체 used/free를 각각 기록해야 한다.

부분 CUDA는 실제 `0 < n < total`과 CUDA model 실행 근거가 있어야 한다. 모든 model
layer가 CUDA인 `n == total`과 CPU+GPU partial offload를 구분한다. CPU backend 로드만으로
model layer가 CPU에 남았다고 해석하지 않는다. `size_vram`은 loaded-model 관측이며
whole-device peak나 독립 per-process VRAM 계측이 아니다. Layer 계획이 실제와 다르면
불일치를 보존하고 성공 조건을 다시 판정한다.

3초 resource sample은 두 sample 사이의 짧은 peak를 놓칠 수 있다. Worker working set·
private bytes·host available RAM·GPU used/free·model `size_vram`은 서로 다른 지표다.
Guard를 둔 사실을 atomic reservation, 무조건적인 OOM 방지나 모든 온도 excursion을
잡는 보장으로 설명하지 않는다.

현재 [resource probe](../tools/hosted/cellivane_resource_probe.py)는 `GlobalMemoryStatusEx`의
host RAM total/available과 `nvidia-smi`의 GPU 0 한 행을 읽는다. GPU 이름·driver·
total/used/free bytes·utilization·온도를 기록하며 power 값만 N/A일 때 null을 허용한다.
필수 query 실패·잘못된 값은 sampling error로 guard를 세운다. Process 목록·PID·serial은
읽지 않으며 **per-process RAM/VRAM은 측정하지 않는다**. Raw GPU query와 typed 값은 같은
sample에 연결하고 `seq`, `elapsed_s`, `query_wall_s`, `stage`를 함께 기록한다.

## 시간·품질·first token의 해석

정확히 계측한 값은 `warmup.wall_s`, 각 corpus row의 `started_s`·`completed_s`·`wall_s`,
`service_start_s`·`service_end_s`와 telemetry의 상대 시각·query wall이다. Model hash는
Sampler 생성 전에 수행하므로 **전체 준비·model hash·독립 load wall은 NOT_MEASURED**다.
Raw backend의 `load_duration`은 존재할 때 원래 field로 보존하지만 전체 CLI 준비 시간과
같은 scope가 아니다. Telemetry stage도 모든 준비·정리 작업을 독립 stopwatch로 계측한
증거는 아니다. Cold-load 성능을 주장하지 않는다. Hash 검사는 OS page cache를 데울 수
있고 Ollama의 prompt/KV reuse도 시간에 영향을 줄 수 있다.

이 경로는 비스트리밍이므로 **TTFT는 NOT_MEASURED**다. 첫 응답 body 완료 시간이나
Ollama `prompt_eval_duration`을 first-token latency로 바꾸어 부르지 않는다. Backend의
`eval_count / eval_duration`은 generation 구간 rate이며 Seed HTTP·audit overhead를
포함한 end-to-end throughput과 다르다. Streaming TTFT는 별도 계약·구현·증거가 필요하다.

정상 HTTP 응답·computed 완료와 정답·지시 준수는 별도로 기록한다. `length`·thinking·
미지원 응답·timeout·자원 guard 중단을 fallback 성공으로 바꾸지 않는다. 같은 corpus의
반복 수는 독립 문제 수가 아니며 15분 관측으로 일반 정확도나 장기 안정성을 보장하지 않는다.

## 실행 방법

[새 launcher](../tools/hosted/cellivane_seed_soak.py)는 Windows에서 실행한다. `--model`은
`4b-q8` 또는 `8b-q4`, 필수 경로는 `--model-file`, `--asset-root`, `--storage-root`다.
`--mode smoke`는 기본 60초·허용 30..300초이고, 기본 mode인 `soak`는 기본 900초·허용
900..3600초다. Seed/worker port의 기본값은 18991/18992이며, 1024..65535의 서로 다른
local port를 `--port`·`--worker-port`로 지정할 수 있다.

기존 검증된 Ollama lab asset root와 정확한 GGUF 파일을 사용한다. 일반 model asset tool의
catalog는 여전히 0.6B/1.7B/4B Q8_0만 지원하므로 그 도구에 `--model 8b-q4`를 전달하지
않는다. Model 파일을 임의로 rename하거나 다른 quantization으로 대신하지 않는다.
기존 lab의 Ollama archive·extracted member와 llamafile/0.6B 준비 검증도 재사용한다.

다음은 repo root의 PowerShell에서 실행하는 예다. 경로 입력은 공개 예시에 개인 cache
경로를 하드코딩하지 않기 위한 것으로, 실제 존재하는 local 절대경로를 입력한다.
결과 root는 기본 local app data 대신 여유 공간이 있는 D: 디렉터리로 설정해도 된다.

```powershell
$taskSoakAssets = Read-Host '기존 검증된 Ollama lab asset root의 절대경로'
$taskFourFile = Read-Host 'Qwen3-4B-Q8_0.gguf의 기존 local 절대경로'
$taskEightFile = Read-Host 'Qwen3-8B-Q4_K_M.gguf의 기존 local 절대경로'
$taskSoakRoot = Join-Path $env:LOCALAPPDATA 'Cellivane/large-model-soak'
py -3 -B tools/hosted/cellivane_seed_soak.py --mode smoke --model 4b-q8 --model-file $taskFourFile --asset-root $taskSoakAssets --storage-root $taskSoakRoot --duration-seconds 60 --port 18991 --worker-port 18992
if ($LASTEXITCODE -ne 0) { throw '4B smoke did not pass; preserve and review its evidence' }
```

4B smoke가 통과한 뒤 별도로 아래를 실행한다. 이 명령은 실제 8B 모델과 소유 프로세스를
기동하며 900초 admission window를 수행한다. Guard·추론·정리·판정 실패 시 nonzero로
끝나며 같은 명령을 자동 재시도하지 않는다.

```powershell
py -3 -B tools/hosted/cellivane_seed_soak.py --mode soak --model 8b-q4 --model-file $taskEightFile --asset-root $taskSoakAssets --storage-root $taskSoakRoot --duration-seconds 900 --port 18991 --worker-port 18992
if ($LASTEXITCODE -ne 0) { throw '8B soak did not pass; preserve and review its evidence' }
```

Alias는 `cellivane-soak-4b-q8:latest` 또는 `cellivane-soak-8b-q4:latest`이며 model identity는
alias 이름이 아니라 실제 GGUF·backend/config hash로 연결한다. Keep-alive 30분을 요청하지만
정상 종료 뒤 소유 Job을 닫고 port·process 정리를 확인한다. 이는 모델의 영구 RAM 상주나
request 취소 기능이 아니다. Bridge는 같은 tensor worker를 Seed 경유·직접 Ollama 두
경로로 호출하므로 독립 모델 둘의 합의나 품질 향상을 검증한 것으로 쓰지 않는다.

## 증거와 현재 결과

Summary는 schema 1, family `cellivane-large-model-soak-v1`이다. Private 결과는 새
`soak-runs/<UUID>/soak.json`, `resources.jsonl`, 원본 backend/startup log와 source snapshot을
연결한다. `source`는 기존 비교 16개에 launcher·probe 2개를 더한 **18개 family**이며
Runtime/Murphy의 26개 또는 26+8개 증거와 다르다. 독립 reader의 구현·재판독 결과는 별도다.

`outcome=COMPLETED`와 `acceptance=PASS`를 구분한다. 후자는 window·drain·최소 완료 수,
모든 corpus row의 computed 완료, `max_tokens=129` 요청의 HTTP 400·추가 dispatch 0개,
계획과 같은 partial CUDA layer 수, telemetry coverage/gap·guard·log, source/model/backend
불변, Seed counters·bridge와 정상 정리 조건까지 확인한다. Runtime failure와 품질 관측을
숨기지 않으며 `exact`는 `text.strip() == expected`의 작은 반복 corpus 관측이다.

| 검증 | 현재 상태 | 필요한 범위 |
|---|---|---|
| 새 launcher / resource probe 계약 | 구현 저장 / PARTIAL | Source·CLI·budget·단위·guard·판정 경계를 읽어 확인 |
| 좁은 model-free fixture | Launcher 8 PASS / probe 10 PASS 보고 | Bridge config 180초, 실제 19/37 placement receipt·stale 33/요청 불일치 거부 포함. 최종 전체 회귀와 구분 |
| 최종 전체 model-free 회귀 | 로컬 Windows 681 PASS / 0 skip / 114.859초 | Terminal unittest 결과와 log SHA를 공개 집계에 기록; 모델 실행·CI와 별도 |
| 최초 4B smoke 진단 | FAIL / 보존 | Corpus computed 111개 뒤 별도 bridge의 240초 설정이 기존 180초 상한을 넘어 거부됨 |
| 최초 8B startup 진단 | FAIL / 보존 | Warmup 1개·CUDA 19/37 이후 catalog의 잘못된 total 33과 불일치. 900초 window 시작 전 실패·소유 process 정리 |
| 최종 교정 source의 4B smoke | 실제·독립 PASS | Corpus computed 114개, admission 60초·기록 service 60.069023초, 실제 CUDA 25/37, source 18개 현재 byte 일치 |
| 새 8B Q4 900초 지속 실행 | 실제 PASS / PARTIAL | Corpus computed 1,476개, 기록 service 900.208646초, 실제 CUDA 21/37, source 18개 현재 byte 일치·정리 확인 |
| 8B 독립 확인 / 새 공개 aggregate | Recorded integrity PASS / 집계 저장 | Source 18개·audit 4,438개·resource 295개·terminal joins. Tensor 재계산·host/endpoint attestation과 별도 |
| 새 revision CI | 별도 확인 | 과거 compare·Runtime·Murphy green으로 대체하지 않음 |

최종 4B smoke run은 `99f8bdfd-f90d-481e-8299-fa80d4d4920a`다. 저장된 독립 stdout verdict는
`recorded-ollama-soak-integrity` 범위의 PASS이고 invocation return code는 0이다.
Audit 352개·resource sample 30개·window 종료 뒤 drain 요청 1개를 확인했다. 실제
수행·정리와 기록 joins를 검증한 범위이며 TTFT·독점 process VRAM·일반 품질·속도 향상·
host/endpoint attestation을 검증한 것은 아니다. 8B 결과와 최종 회귀는 각각 별도 원문으로 확인했다.

## 최종 측정과 해석

8B 최종 run은 `b449a358-2941-4091-81d1-2bb4b65bdf12`다. Producer acceptance와 독립
`recorded-ollama-soak-integrity` reader가 모두 PASS이며 reader exit code는 0이다.
두 최종 run은 같은 source 18개와 각각의 model/backend/config identity를 확인했다.
아래 HTTP wall은 비스트리밍 요청 완료 시간이며 p95는 nearest-rank다. 4B/8B의 quantization·
offload layer·실행 길이가 다르고 backend KV reuse도 통제하지 않았으므로 두 열을
모델 크기만의 성능·품질 비교로 해석하지 않는다.

| 최종 관측 | 4B Q8_0 smoke | 8B Q4_K_M soak |
|---|---:|---:|
| Admission window / 기록 service | 60초 / 60.069023초 | 900초 / 900.208646초 |
| Corpus computed | 114 | 1,476 |
| Exact-format / corpus 응답 | 106 / 114 | 1,371 / 1,476 |
| HTTP wall p50 / p95 | 0.280373 / 0.496847초 | 0.297961 / 0.646282초 |
| 실제 CUDA offload | 25 / 37 | 21 / 37 |
| Service / 전체 resource sample | 20 / 30 | 283 / 295 |
| Service 최소 host available RAM | 17,806,888,960 bytes | 17,245,847,552 bytes |
| Service 최소 device free VRAM | 2,447,376,384 bytes | 2,619,342,848 bytes |
| Service 최대 device used VRAM | 5,847,908,352 bytes | 5,675,941,888 bytes |
| Service 최고 GPU 온도 | 44°C | 45°C |

두 run은 고유 14문제를 반복했다. 8B의 불일치 105개는 모두 같은 `list-count` 소수 개수
문제의 반복 실패이고 4B도 그 문제의 8회 응답 모두 불일치였다. 나머지 고정 case의
일치는 이 corpus 안의 관측이다. 1,476개의 독립 문제를 검증했거나 모든 답변이 옳았다는
뜻이 아니며 품질 개선을 주장하지 않는다. 원시 prompt/answer는 private evidence에 남긴다.

8B 서비스 구간에서 resource guard는 발동하지 않았고 관측된 RAM·VRAM·온도는 위
guard 범위 안이었다. 이는 283개 sample에 대한 관측이며 연속 peak·메모리 누수 부재·
향후 OOM 방지의 증명이 아니다. Device used/free에는 다른 프로세스도 포함된다.
Warmup 1개와 별도 bridge의 Seed 경유 1개를 더한 최종 Seed computed/backend_calls는
4B 116개, 8B 1,478개다. 두 run 모두 `max_tokens=129` 요청 거부 1개, cache hit·failure·timeout은
0개이며 active/inflight/waiter 0·closed·소유 Job 정리·port 닫힘을 확인했다.

8B는 window 뒤에 완료된 corpus 요청이 없어 `drained_requests=0`이다. 기록 service의
0.208646초 초과에는 마지막 응답 이후 audit/log 작업이 포함된다. 이를 GPU drain 시간으로
부르지 않는다. 4B의 window 뒤 완료 요청은 1개다. 준비·warmup·별도 bridge 시간은
위 service와 분리되며 전체 준비 stopwatch의 미측정 경계도 유지한다.

### 완료 수 감소와 응답 지연의 구분

8B 원문에서 service 시작 기준 반열린 구간 `[0,60)`과 `[840,900)`을 각각 계산했다.
Latency는 해당 구간에 **시작한** 요청으로 계산하고 완료 수는 완료 timestamp를 별도로
센다. 실시간 progress 출력의 누적 수를 1분 구간 수로 대신하지 않는다.

| 기록 기반 통계 | 첫 1분 | 마지막 1분 |
|---|---:|---:|
| 시작 / 완료 요청 수 | 107 / 107 | 82 / 83 |
| HTTP wall p50 | 0.3226963초 | 0.2948355초 |
| Backend elapsed p50 | 0.281초 | 0.266초 |
| 다음 시작 − 이전 완료 p50 | 0.1776349초 | 0.3485133초 |

분당 완료 수는 줄었지만 이 두 구간의 HTTP·backend 지연 중앙값은 늘지 않았다.
요청 사이 간격에는 최소 시작 간격 0.5초의 pacing과 producer 작업이 포함된다.
이상적 최소 pacing을 초과한 간격의 p50도 0.0127242초에서 0.1552611초로 늘었으나,
이는 원문 timestamp에서 계산한 값이지 GPU idle이나 특정 함수의 소요 시간을 직접 잰
값이 아니다. Producer가 매 완료마다 커지는 backend log 전체를 읽어 fatal 패턴을
검사하는 것은 가능한 harness overhead 원인이다. 해당 단계 시간을 따로 재지 않았으므로
원인으로 확정하지 않는다. 안정된 throughput·GPU 성능 저하·thermal throttling을
주장하지 않으며 다음 실험에서는 이 비 backend 구간을 먼저 계측해야 한다.

## 보존된 진단과 공개 경계

최초 진단 run은 `b55bb992-18fa-40d2-a443-2dc14d811600`이다. 응답 loop의 computed 수를
전체 acceptance PASS로 바꾸지 않는다. 새 producer에서 bridge 구성을 180초로 수정했고
기존 config loader로 그 구성을 검사하는 fixture를 추가했다. 최초 실패·당시 source와
수정 뒤 재실행은 별도 증거로 보존하며, 최종 공개 집계에도 진단 실패를 함께 기록한다.

8B startup 진단 `0024be9a-0fa8-4a1d-8701-4b47b6531905`는 잘못 입력한 catalog total 33을
실제 native 19/37 기록과 비교하는 단계에서 실패했다. 15분 지속 시험을 수행한 결과나
GPU 미지원·메모리 부족 판정이 아니다. 원본 GGUF를 바꾸지 않고 새 producer의 8B total을
37로 교정했으며, 실제 placement receipt·오래된 total·요청 layer 불일치를 검사하는
fixture를 추가했다. 교정 전 source·원문과 교정 뒤 재실행을 별도로 보존한다.

Terminal 판정은 단순히 loop가 끝난 것과 구분한다. 최소 computed 수·거부·실패·timeout·
guard 상태, active/inflight/waiter와 cache counter, owned process·port 정리를 함께
확인한다. 관측이 누락됐거나 time window·offload가 불명확하면 그 한계를 결과에 남긴다.
독립 기록 확인은 live tensor 재계산, process/PID attestation, 미래 성능 보장과 구분한다.

Public evidence에는 allowlisted 설정·모델/source hash·run ID·시간·resource 통계·명시적
판정 범위만 담는다. 개인 절대경로·PID·원시 prompt/answer·환경 dump·engine log·모델/
binary는 private evidence로 보존한다. 실패와 해당 source snapshot을 삭제하거나 새
PASS로 덮어쓰지 않는다. 기존 공개 집계도 변경하지 않는다.
