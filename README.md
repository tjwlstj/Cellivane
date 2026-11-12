# Cellivane · 셀리베인

로컬 AI가 작업 환경과 상태를 이해하고, 위임받은 일을 수행하며, 사용자 개입과 재시작 뒤에도 실제 결과를 확인할 수 있는 운영 환경입니다.

**현재 PARTIAL: 기존 AIOS·서빙·Seed 작업을 출처가 있는 공개 소스 기준선으로 모으는 단계입니다.** 설치 가능한 통합 제품, 심핵, 위임된 고권한 집행, 다중 하드웨어와 독자 native OS 수락은 아직 완료되지 않았습니다.

Cellivane은 제품 이름, AIOS는 기존 모듈·ABI·CLI·프로토콜의 기술·호환 이름입니다. 체시(Chesi)는 사용자와 함께 작업하는 동반자입니다.

## 시작점

- [제품 목적과 구성요소](docs/PRODUCT.md)
- [통합 순서와 완료 조건](docs/ROADMAP.md)
- [개발 환경 준비](docs/DEVELOPMENT.md)
- [소스 출처·검증 경계](docs/provenance/MIGRATION.md)
- [가져온 파일의 SHA256 manifest](docs/provenance/source-snapshot.json)
- [이번 준비·검증 기록](docs/provenance/PREPARATION_20261112.md)
- [이전 AIOS README](docs/history/AIOS_README_20261012.md) — 가져온 시점의 역사 기록

## 구성

| 경로 | 역할 | 경계 |
|---|---|---|
| hosted/ | Linux Runtime·Console·Task·어댑터 | 제한된 실제 모델·취소 증거와 후속 fixture, 전체 제품 수락 별도 |
| kernel/·os/ | 독자 x86_64 커널·제한된 사용자 실행 | 최소 계층·binding·ring3 proof, 범용 storage/process·실기기 후속 |
| components/seed/ | 독립 Seed 최신 소스 snapshot | 요청 제한·완료 cache·동일 요청 합류·효율 실험, 별도 프로세스 검증 |
| models/·store/ | manifest·catalog | 가중치·엔진 배포물 미포함 |
| tools/ | 빌드·실행·독립 판정·개발 진단 | 실제 실행·fixture·과거 기록 구분 |

제품 구성요소로 평가할 최신 Seed는 components/seed에 있습니다. hosted/experimental의 초기 Bridge·Seed는 당시 실험을 보존합니다. 두 snapshot을 같은 Python 프로세스의 import 경로로 합치지 않습니다.

## 개발 시작

Python fixture 경로는 **CPython 3.11 표준 라이브러리**를 사용합니다. 기본 준비는 모델 다운로드·실행이나 pip 설치를 하지 않습니다.

~~~powershell
.\dev.ps1 bootstrap
.\dev.ps1 doctor
.\dev.ps1 hosted
.\dev.ps1 testkit
.\dev.ps1 seed
~~~

Linux:

~~~bash
python3.11 -m venv --without-pip .venv
.venv/bin/python -B tools/workspace/doctor.py
.venv/bin/python -B tools/workspace/check.py --suite all
~~~

로그와 상세 진단은 로컬 build/workspace에 기록합니다. optional compiled worker가 없으면 해당 native protocol 검사는 skip될 수 있습니다. fixture PASS는 실제 모델·GPU·QEMU·UEFI 설치 수락을 뜻하지 않습니다.

## 검증·공개 범위

기존 TaskSmoke·서빙 회귀·Seed 배치 개선은 각 source와 조건에 한정된 역사적 증거입니다. 새 snapshot의 결과와 exact-commit CI를 별도로 기록합니다.

원본 Git history, 개인 원시 로그·세션 bundle, 모델, 엔진/toolchain binaries, 디스크 이미지는 공개 소스에 포함하지 않습니다. 원본 작업과 선택 소스 복구 사본은 로컬에 보존했습니다.

## License

기존 AIOS README의 MIT 의도를 정식 [MIT License](LICENSE)로 보완했습니다. [Seed MIT 고지](components/seed/LICENSE)를 보존합니다. 외부 모델·엔진·Linux·QEMU·toolchain은 별도 라이선스를 따르며 이 저장소가 재배포·재허가하지 않습니다. resource의 code_import=false 경계는 유지합니다.
