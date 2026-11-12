# 2026-11-12 공개 기준선 준비·검증

상태: 로컬 소스·도구 준비 및 공개 beta 게시 완료, 통합 제품 PARTIAL. 최초 공개 CI의 실패와 호환 수정은 [CI 기록](CI_BOOTSTRAP_20261112.md)을 따른다.

## 가져온 범위

- AIOS serving 현재 파일 473개, 독립 Seed 117개, 심핵 설계 1개: 합계 591개.
- source와 exported SHA256·bytes를 기록했다. 문서/ignore의 공개 정리는 명시 refresh 이력으로 남긴다.
- 원본 source와 선택 소스의 별도 복구 사본을 로컬에 보존했다. 기존 저장소와 branches를 변경하지 않았다.
- 원시 실행 증거·Git history·세션 bundle·가중치·엔진/toolchain binary·disk image는 공개하지 않는다.

## 개발 도구

CPython 3.11.9의 pip 없는 .venv, Git, C:의 x86_64-elf cross toolchain 복사본을 준비했다. Make·NASM·QEMU는 기존 C: 설치를 참조한다.

cross GCC/ld/objcopy 실행과 Python 개발 진입을 확인했다. cross toolchain은 gitignored 로컬 파일 509개·255453135 bytes다. GRUB/xorriso는 준비되지 않았고, WSL은 이 세션에서 접근하지 못했다. native binary build는 한 번 시도했으나 MSYS shell의 named-object 권한 거부로 컴파일 시작 전 실패했다. ISO/QEMU/UEFI 설치·모델 실행은 하지 않았다.

## 이번 위치에서 실행한 검사

| 검사 | 결과 | 범위 |
|---|---|---|
| workspace doctor/check/public-audit tests | 30 PASS, 0 skip | 새 개발 진입과 공개 guard의 positive/negative 사례 |
| 공개 source audit | PASS | source manifest·정형식 credential/개인 경로·payload 검사, 7개 exact synthetic fixture 예외 |
| Python AST | 315개 PASS | 컴파일/실행 수락과 별도 |
| Linux resource policy guard | PASS, 13개 resource | source-only/code_import=false 계약 |
| Testkit 전체 | 157개 중 1 FAIL | Windows owned child의 종료 신호 확인. 원본 실패 보존 |
| Testkit 전체 순차 재실행 | 157 PASS, 0 skip, 3.687초 | 최초 실패와 함께 보존; 간헐 종료 확인 문제는 미해결 |
| 동일 Testkit 실패 항목 단독 | 1 PASS, 0.250초 | 전체 suite PASS로 승격하지 않음 |
| Hosted 전체 | 미완료 FAIL, exit 3221225480 | Windows handle 종료 오류, terminal unittest summary 없음 |
| Seed 전체 | 미완료 FAIL, exit 3221225480 | Windows handle 종료 오류, terminal unittest summary 없음 |
| Seed HTTP proxy fixture 단독 | 1 FAIL | ANSWERED 대신 UNKNOWN. 이 세션 통신 제약의 영향과 구현 문제를 추가 분리해야 함 |
| H1 fixtures 최초 실행 | HEAD 부재로 FAIL | 최초 준비 단계, 원본 보존 |
| H1 fixtures commit 후 새 실행 | 12/12 기대 결과 일치 PASS | source 기준선의 관측·관리 trace 계약 |
| Git 최초 새 checkout | FAIL | request_state.py의 이전 index LF 변환을 발견 |
| Git index 재정규화 후 새 checkout | PASS | 원본 CRLF bytes를 index에 다시 저장, autocrlf=true에서도 imported591 hash/bytes 일치 |

로컬 raw 로그·상세 도구 경로는 gitignored build/workspace에 보존한다. 전체 suite가 끝나지 않았으므로 과거 1122/815 결과를 이 새 snapshot의 PASS로 쓰지 않는다.

Testkit의 Job active-process drain과 retained process-handle signaled 확인 사이에는 별도 완료 대기가 없어 race 가능성이 있다. 단독 PASS만으로 병렬 부하가 원인이라고 확정하거나 cleanup의 안전성을 승격하지 않는다. 최초 준비 snapshot에서는 가져온 runtime/tests bytes를 변경하지 않았다. 이후 최초 CI에서 확인한 시험 fixture 두 파일과 build flag 수정은 별도 검토 이력으로 기록한다.

## 남은 작업

1. 공개 저장소와 최초 beta 게시를 확인했다. 최초 CI 호환 수정 후 새 exact commit의 결과를 확인한다.
2. Windows 전체 회귀의 handle 종료·HTTP UNKNOWN 원인을 분리한다.
3. GRUB/xorriso와 Linux native build/VM 경로를 별도 준비·검증한다.
4. 제품 수락은 [ROADMAP](../ROADMAP.md)의 고정 UEFI 설치·유용한 Task부터 진행한다.

## 줄바꿈·서식 보존

기존 runtime/tests bytes를 보존하기 위해 기본 Git 변환은 비활성화하고 명시된 LF/CRLF 규칙을 유지했다. request_state.py는 source manifest의 CRLF bytes를 보존한다. 새 작성 파일의 diff --check는 통과했다. 초기 전체 import의 기존 공백/EOF 서식 진단은 build/workspace/staged-whitespace.txt에 보존했으며 source bytes를 일괄 정리하지 않았다.
