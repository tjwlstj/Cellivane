# Cellivane 제품 기준

작성: 2026-11-12. 새 공개판의 제품 목적과 첫 통합 수락 범위 정본이다. 가져온 상세 설계의 과거 '현재/다음'을 새 전역 큐로 실행하지 않는다.

Cellivane은 로컬 AI가 자신의 작업 공간과 상태를 이해하고, 사용자가 위임한 범위에서 활동하며, 중단·교체·재시작 뒤 실제 결과를 확인할 수 있는 운영 환경을 만든다.

장기 목표는 심핵의 지속 ID·사용자 기준·약속·사건 이력과 주의 신호, 위임·철회 가능한 높은 권한, 독자 native OS의 명시적 실행 책임이다. 현재 목표 전체는 PLANNED다. Linux-hosted 제품 수락과 native 실행 수락을 별개로 기록한다.

## 구성요소 책임

| 구성요소 | 책임 |
|---|---|
| 체시·Console | 의도·대화·작업·진행·개입·결과 설명 |
| Runtime·Task | 접수·dispatch·진행·결과·취소·재접속의 실제 상태 |
| Kernel Room | Room → Cell → Node → NodeBit 식별·관계·세대·유효성 |
| Serving·Seed | backend 계약·요청 한도·검증된 결과 재사용 |
| 심핵 | 지속 ID·기준·사건 이력·주의·재검토 후보 |
| Native Kernel | 독자 실행·메모리·장치·권한 책임과 관리 불변식의 proof |
| Testkit | 원본 실행과 독립 verdict의 대조 |

Task, Session, EngineInstance, agent ID는 canonical Node ID와 별도다. 표시 이름과 기능 존재는 권한을 만들지 않는다. 상세 관리 의미는 [관리 모델](kernel-room/kernel_room_management_model_ko.md)을 유지한다.

## 공통 계약

1. 안정된 agent ID와 실행 epoch, backend instance/generation을 구분한다.
2. durable acceptance 후 실행하고 완료·실패·취소·UNKNOWN을 보존한다.
3. 관측에는 source·시점·유효성·세대를 붙인다.
4. 위임·철회·요청 취소·worker 종료·backend 종료를 각각 확인한다.
5. source·model·backend·image와 실제 증거·독립 verdict를 연결한다.

## 첫 제품 수락 장면

고정 UEFI 환경에 설치한 Cellivane에서 체시가 실제 상태와 허용된 로그를 읽어 근거 있는 보고서를 작성·저장한다. 사용자가 중단하거나 실행기가 교체되면 확인된 상태를 설명하고, 재접속 뒤 완료·미완료·UNKNOWN과 저장 결과를 구별한다.

현재 구현은 이 장면의 일부 기반을 가진 PARTIAL이며 이 새 snapshot에서 전체 장면을 성공한 것으로 기록하지 않는다.
