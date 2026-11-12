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
