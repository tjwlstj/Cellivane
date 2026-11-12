# Cellivane Seed 독립 공개 베타

기준일: 2026-10-12. 상태: **PARTIAL / 독립 hosted 실험 공개**.

Seed와 브릿지의 독립 공개 저장소는
[tjwlstj/cellivane-seed](https://github.com/tjwlstj/cellivane-seed)이며 기본 브랜치는
`beta`다. 공개 소스 기준은
[`59c9bcd530ff1250b2117b32dfc9da33e97362bd`](https://github.com/tjwlstj/cellivane-seed/commit/59c9bcd530ff1250b2117b32dfc9da33e97362bd)다.
작업 경로는 `D:/AIOS/cellivane-seed-public`이다. 기존 AIOS 작업트리의 변경사항과
이력은 공개 export에 섞지 않았으며 AIOS `main`은 이동하지 않았다.

새 공개 경로에는 원래 Seed/bridge, portable 저장 경로, Ollama 서브엔진 adapter,
`cpu`·`hybrid`·`auto` 요청 배치 계획, 고정 모델 다운로드 도구, 비교 실행기와
독립 비교 검증기가 있다. 텐서 계산은 고정 외부 Ollama v0.40.2가 담당한다.
Strata의 MoE expert cache나 multi-GPU 구현을 복제한 엔진이 아니다.

Qwen3 Q8_0 0.6B·1.7B·4B CPU, 4B CPU+CUDA 14/37 layer, 1.7B CUDA auto 29/29
layer의 다섯 실행에서 각각 12문항을 두 번 실행했다. exact-format 일치는 순서대로
6/24·14/24·22/24·22/24·14/24다. Seed 완료 결과 cache는 껐으며 backend prompt/KV
재사용 가능성은 유지한다. 작은 고정 표본이며 일반 정확도나 속도 보장이 아니다.

다섯 실행의 요청·원문·Seed event·배치 로그·`/api/ps`·bridge journal을 독립
재판독하여 PASS를 확인했다. 16개 실행 소스의 현재 hash도 대조했다. 로컬 최종
Windows 회귀는 280 PASS/0 skip이다. 원문과 모델은 D:에 보관하며 공개 저장소에는
개인 경로·PID·원문 응답·실행 로그 대신 allowlist 집계만 있다.

자세한 수치·재현 명령·한계는 공개
[BENCHMARKS.md](https://github.com/tjwlstj/cellivane-seed/blob/59c9bcd530ff1250b2117b32dfc9da33e97362bd/docs/BENCHMARKS.md)와
[ARCHITECTURE.md](https://github.com/tjwlstj/cellivane-seed/blob/59c9bcd530ff1250b2117b32dfc9da33e97362bd/docs/ARCHITECTURE.md)를 따른다.
같은 commit의 공개 [CI 38192783515](https://github.com/tjwlstj/cellivane-seed/actions/runs/38192783515)는
Windows 280개/0 skip, Ubuntu 280개/15 platform skip으로 terminal success다.
모델 실행은 로컬 Windows 결과이며 CI는 stdlib/loopback fixture 검증이다.

이 공개 실험은 native Kernel Room, 공개 Linux 이미지, endpoint/PID attestation,
backend stop/KV release, MTP, actual multi-GPU 또는 AMD/Intel/Apple 실행의
qualification을 승격하지 않는다. 기존 0.1.0 원문 bundle과 이번 독립 공개
source/evidence 경계를 유지한다.
