# 2026-11-12 최초 공개 CI와 호환 수정

공개 저장소: https://github.com/tjwlstj/Cellivane

최초 공개 beta: ff3d4353741977872072514ec24afa3d476dc4e0.
로컬 beta·origin/beta·원격 ref와 전체 tree 7c1cea6acd99aca1a02177a27e36da83b93c606b의 일치, 공개 파일 608개와 로컬 전용 payload 제외를 확인했다.

## 최초 CI 실패의 보존

- [Linux Boot Check run 43221842581](https://github.com/tjwlstj/Cellivane/actions/runs/43221842581): native build에서 최신 cc의 기본 C23 모드와 기존 bool typedef가 충돌했다. H1 Windows/Linux fixture·parity, static analysis, Ubuntu OS tools는 별도 성공이다.
- [Workspace and Seed run 43221842565](https://github.com/tjwlstj/Cellivane/actions/runs/43221842565): workspace Windows/Linux 성공. Seed Windows는 815개 중 801 실행 PASS·compiled worker 14 skip. Seed Linux는 13 failure·4 error·33 skip으로 실패했다.

Seed 실패는 정상 synthetic receipt가 현재 Python 실행 파일의 별칭 경로를 기록해 기존 symlink 거부 계약과 충돌한 경로로 좁혔다. production verifier의 거부 조건을 완화하지 않는다.

## 검토한 최소 수정

| 파일 | 수정 | 유지한 경계 |
|---|---|---|
| kernel/Makefile | GNU C11을 명시 | 커널 C body·header·ABI·enum 변경 없음 |
| components/seed/tools/hosted/tests/test_cellivane_efficiency_matrix.py | 신뢰한 현재 interpreter fixture의 경로를 resolve(strict=True)로 준비 | production collector·verifier·path guard 불변 |
| components/seed/tools/hosted/tests/test_cellivane_efficiency_verifier.py | 같은 fixture 경로 정규화 | 실제 증거의 symlink 거부 유지 |

원본 source hash를 보존하고, 세 파일의 검토된 export hash 변경만 source-snapshot의 reviewed_source_changes에 기록한다. 일반 public_audit의 코드 drift 자동 refresh 금지 규칙은 유지한다.

## 로컬 확인

- 실제 GCC 15로 types.h fixture를 검사: GNU C23 실패·GNU C11 성공.
- C: cross compiler로 Makefile의 같은 flags와 C source 42개 syntax-only 검사 성공. link·native VM 수락과 별도다.
- Seed matrix 12개·verifier 55개, 합계 67 PASS·0 skip을 확인했다. 이 수정 SHA의 원격 CI는 별도 확인하며 최초 실패는 위 run에 보존한다.

프로젝트 성숙도는 PARTIAL이다. CI 호환 수정이 새 실제 모델·GPU·운영 이미지·UEFI·물리 설치나 심핵·고권한 실행을 검증한 것은 아니다.

## d52dc6c의 Seed 단일 timeout과 시험 여유

[Workspace and Seed run 43226550286](https://github.com/tjwlstj/Cellivane/actions/runs/43226550286)은 workspace 두 플랫폼과 Seed Windows(815개, 14 skip)가 성공했다. Seed Ubuntu는 815개 중 33 skip과 단일 ERROR로 실패했다. 기존 interpreter symlink 오류는 재발하지 않았다.

실패한 test_partial_pipe_writes_preserve_exact_raw_command는 fake process와 이미 queue에 넣은 응답을 쓰지만, 기본 80ms deadline 안에서 durable stdin fsync와 writer scheduling까지 처리한다. 실패는 응답 대기 전 remaining <= 0 분기다. fsync와 scheduling 각각의 지연은 이 CI 로그로 특정할 수 없다.

정확한 command/log bytes를 확인하는 이 성공 fixture에만 timeout=2를 명시했다. production transport, 80ms timeout·blocked-write fault tests, 250ms remaining-budget test는 변경하지 않았다. 원본 source hash를 보존하고 네 번째 검토 대상 source overlay로 기록한다.

실제 fsync 후 120ms 지연을 주입해 수정 전 timeout과 수정 후 성공을 확인했고, transport module 전체도 성공했다. 새 수정 SHA의 전체 CI 결과는 별도 확인한다. 최초 실패 run은 그대로 보존한다.

## 원격 CPU ISA와 합성 ZIP 시각의 재현성

[d52dc6c Linux Boot Check run 43226550465](https://github.com/tjwlstj/Cellivane/actions/runs/43226550465)의 kernel compile/link/ISO는 성공했지만 기본 CPU의 QEMU 부팅은 실패했다. 내려받은 동일 ISO를 로컬 QEMU에서 재현하자 console_write_hex의 BMI2 shrx 명령(RIP 0x121ae4)에서 최초 #UD가 발생하고, 초기 IDT 부재로 double/triple fault가 이어졌다. 같은 호스트의 cross GCC 14 빌드는 BIOS 최소 부팅을 통과했다. Makefile에 -march=x86-64를 명시해 커널 기본 ISA를 고정한다. CPU profile을 확대하거나 verdict를 완화하지 않는다.

[4ce1255 Workspace and Seed run 43227181603](https://github.com/tjwlstj/Cellivane/actions/runs/43227181603)은 workspace 양쪽·Seed Ubuntu(815개, 33 skip)가 성공했다. Seed Windows는 815개 중 14 skip·단일 backend-archive-pin ERROR로 실패했다. soak fixture 두 ZIP의 payload가 같아도 생성 시각이 DOS 2초 경계를 넘으면 archive hash가 달라졌다. 서로 다른 timestamp를 주입해 실패를 재현했다. 합성 ZIP member의 시각만 고정한 뒤 같은 재현과 soak verifier 32개가 성공했다. production archive pin·tamper 검증은 그대로 유지한다.

모든 최초 실패와 원본 source hash를 보존한다. 새 수정 SHA의 전체 CI 수락은 해당 commit의 원격 terminal 결과로만 판정한다.

## 로컬 Seed 전체 회귀와 owner/waiter 시험 동기화

0eb0a12의 원격 Workspace/Seed 네 job은 성공했다. 별도 로컬 Seed 전체 실행은 terminal까지 진행해 815개 중 800 PASS·1 failure·14 skip을 기록했다. 실패는 test_waiter_timeout_releases_only_waiter_and_does_not_cancel_owner다. 처음의 invalid-handle 중단과 다른 실제 시험 실패이며 원본 로그를 보존한다.

fixture는 active 상태가 공개되면 owner의 제한시간 측정과 backend가 이미 시작했다고 가정했다. 실제 core는 active를 공개한 뒤 lock을 나오고 monotonic 시작 시각을 잡는다. 그 사이 owner를 200ms 지연시키면 waiter가 먼저 만료된 뒤 owner가 자신의 제한시간 안에 정상 반환할 수 있어 기존 assertion이 실패한다. 이 스케줄을 core.time에만 proxy를 넣어 결정적으로 재현했다. 최초 전체 실행에는 이 시각별 관측이 없으므로 같은 원인이 실제 발생했다고 단정하지 않는다.

fixture만 backend entered Event를 기다린 뒤 waiter 제한시간을 검사하도록 고쳤다. finally의 gate release·join, owner 종료·backend-deadline, 빈 cache와 backend 호출 1회 확인을 유지한다. 같은 선행 지연에서 수정 후 1 PASS와 core module 20 PASS를 확인했다. production core와 제한시간·취소·캐시 계약은 변경하지 않았다. 새 수정 SHA의 전체 원격 회귀는 별도 확인한다.
