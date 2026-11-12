# Cellivane public workspace instructions

- 매 턴 체시 스킬이 있으면 적용한다.
- 새 작업 전 branch, HEAD, upstream, dirty state를 확인하고 사용자 변경을 보존한다.
- 새 공개판 제품 목적은 docs/PRODUCT.md, 유일한 전역 큐는 docs/ROADMAP.md다.
- 개발·출처·검증은 docs/DEVELOPMENT.md와 docs/provenance/MIGRATION.md에서 확인한다.
- 가져온 AIOS 상세 정본은 기술 계약·불변식을 소유한다. 과거 현재/다음 작업을 새 큐로 실행하지 않는다.
- Room → Cell → Node → NodeBit와 Task/Session/EngineInstance ID를 구분한다.
- 구현은 CURRENT/PARTIAL/SCAFFOLD/PLANNED, 선택 연구는 RESEARCH로 기록한다.
- components/seed는 독립 snapshot이며 root hosted와 별도 subprocess에서 검증한다.
- 개인 원자료·credentials·모델·엔진/toolchain binaries·image를 공개 파일에 넣지 않는다.
- source-snapshot의 original hash는 보존한다. 공개 문서 편집은 명시 refresh와 이유를 기록한다.
- 작업 브랜치는 beta. 검증 후 beta에 게시하고 exact-SHA CI를 확인한다.
- main 승격은 사용자의 명시 요청과 beta SHA 원격 검증 후 같은 SHA로 fast-forward한다.
- 원본 AIOS/Seed 저장소와 작업트리는 새 공개판 작업 중 변경하지 않는다.
- native/QEMU/모델/UEFI 실행을 하지 않았으면 명시한다. fixture는 실제 제품 수락을 대신하지 않는다.
- 영역별 작업은 .agents/skills의 최소 해당 스킬을 끝까지 읽고 적용한다.
