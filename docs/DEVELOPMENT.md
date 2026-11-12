# 개발 환경 준비

기준: CPython 3.11, Git. Python fixture 경로는 표준 라이브러리를 사용한다.

## Windows

~~~powershell
.\dev.ps1 bootstrap
.\dev.ps1 doctor
.\dev.ps1 hosted
.\dev.ps1 testkit
.\dev.ps1 seed
~~~

bootstrap은 작업 폴더 안에 pip 없는 .venv와 로컬 도구 설정을 준비한다. 시스템 PATH·기존 Python 설치를 바꾸지 않는다. py launcher가 설치를 찾지 못하면 알려진 CPython 설치를 탐색한다.

.cellivane/local-tools.json, .venv/, .toolchain/, build/는 로컬 전용이다. 경로가 바뀌면 doctor로 확인한다. skip·도구 부재를 PASS로 읽지 않는다.

## Linux

~~~bash
python3.11 -m venv --without-pip .venv
.venv/bin/python -B tools/workspace/doctor.py
.venv/bin/python -B tools/workspace/check.py --suite all
~~~

hosted, testkit, Seed는 각각 별도 Python subprocess에서 실행한다. 두 snapshot의 동일한 cellivane_* 모듈을 한 프로세스로 합치지 않는다. 로그와 exit·기간은 build/workspace 아래에 보존한다.

## 선택 native 도구

native cross build에는 x86_64-elf GCC/binutils, Make·NASM이 필요하다. 커널 Makefile은 GNU C11 모드를 명시해 새 컴파일러의 기본 C23과 기존 타입 계약이 충돌하지 않게 한다. Windows 스크립트는 AIOS_X86_64_ELF_ROOT 또는 .toolchain/x86_64-elf를 지원한다. 일반 MinGW GCC를 cross compiler로 취급하지 않는다.

ISO 생성과 VM에는 GRUB·xorriso·QEMU 등이 별도로 필요하다. 찾은 QEMU/UEFI 펌웨어는 개발 도구이며 새 UEFI 설치 검증의 증거가 아니다. 이번 세션의 MSYS xorriso/GRUB·WSL 제한은 준비 기록을 따른다.

모델·엔진은 각 manifest·hash·라이선스를 확인해 별도로 준비한다. 기본 개발 준비는 모델 실행·다운로드를 하지 않는다.

## 게시

beta를 작업·공개 기준 브랜치로 사용한다. 공개 전 source-snapshot 검사, public_audit, 관련 회귀, git diff --check를 통과시킨다. 게시 후 exact commit의 CI를 확인한다. 기존 저장소의 main/beta는 변경하지 않는다.
