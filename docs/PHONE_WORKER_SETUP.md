# 폰 워커 — 2단계 발판과 게이트

이관 계획의 **2단계**다. 여기서 하는 일은 매매가 아니라 딱 하나다:

> **안드로이드가 상주 프로세스를 사흘 동안 죽이지 않는가?**

3일 무사고를 못 채우면 폰 워커로 가지 않고 GCP `e2-micro`로 전환한다.
월 ₩400~2,000을 아끼려고 돈 경로를 불안정한 런타임에 올릴 이유가 없다.
**이 판단을 미리 정해 두는 것이 이 단계의 요점이다** — 나중에 "거의 됐는데"로
넘어가지 않기 위해서.

이 단계에서는 **시크릿을 폰에 넣지 않는다.** KIS 키도 GH_PAT도 아직이다.
살아남는지만 본다.

---

## 왜 될 가능성이 있나

안드로이드 Doze의 진입 조건은 **화면 꺼짐 + 미충전 + 정지**다. 상시 충전이면
Doze 자체가 성립하지 않는다. 남는 위험은 둘이다.

| 위험 | 대응 |
|---|---|
| OEM 킬러 (삼성 "잠자는 앱", 샤오미 MIUI 등) | 배터리 최적화 예외 + 절전 목록에서 제외 |
| 메모리 압박 시 LMK | `termux-wake-lock` + 포그라운드 알림 유지 |

둘 다 설정으로 누를 수 있지만 **기기·OS마다 다르다.** 그래서 재본다.

---

## 1. 설치

**Termux는 Play 스토어 버전을 쓰면 안 된다.** 그 빌드는 오래전에 갱신이 끊겼고
패키지 설치가 깨진다. F-Droid 또는 GitHub 릴리스에서 받는다.

- Termux — https://f-droid.org/packages/com.termux/
- Termux:Boot — https://f-droid.org/packages/com.termux.boot/ (재부팅 자동 시작)

두 앱은 **같은 서명**이어야 하므로 둘 다 F-Droid에서 받는다(하나만 Play에서
받으면 설치가 거부된다).

```bash
pkg update && pkg upgrade -y
pkg install -y python git
python --version        # 3.11 이상이면 충분
```

## 2. 안드로이드 설정 (여기가 진짜 작업이다)

기종마다 경로 이름이 다르다. 아래는 의미로 적었으니 해당하는 항목을 찾는다.

- [ ] **배터리 최적화 예외** — 설정 → 앱 → Termux → 배터리 → *제한 없음*
- [ ] **절전 목록에서 제외** — 삼성이면 설정 → 배터리 → 백그라운드 사용 제한 →
      *잠자는 앱* / *심층 절전 앱* 목록에 Termux가 **없어야** 한다
- [ ] **자동 OS 업데이트 끄기** — 재부팅이 소크를 끊는다
- [ ] **상시 충전 연결** — Doze를 피하는 조건이므로 협상 불가
- [ ] **Wi-Fi 절전 끄기** (있으면) — 지금은 네트워크를 안 쓰지만 3단계에서 필요하다

## 3. Tailscale (관측 + 인바운드)

지금 당장은 필수가 아니지만 **여기서 같이 해 두는 편이 낫다.** 3단계부터
로그를 봐야 하는데, 폰에 들어갈 길이 없으면 그때 다시 폰을 만져야 한다.

- Tailscale 앱 설치 후 로그인 (개인 무료 티어로 충분)
- Termux에서 `pkg install openssh && sshd`, `whoami`로 사용자 확인
- PC에서 `ssh <user>@<tailscale-ip> -p 8022`로 붙는지 확인

이걸로 CGNAT 뒤에 있는 폰에 인바운드가 뚫린다 — 4단계에서 Actions 잡이 워커의
토큰을 받아 갈 때 쓰는 경로와 같다.

## 4. 소크 시작

```bash
git clone https://github.com/hoonnamkoong/stockbot.git
cd stockbot
termux-wake-lock                       # 이거 없으면 화면 끄는 순간 조용히 멈춘다
python -u scripts/phone_soak.py --run  # 그대로 두고 화면만 끈다
```

재부팅에도 살아남게 하려면 (권장):

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/soak.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd ~/stockbot && python -u scripts/phone_soak.py --run >> ~/soak_stdout.log 2>&1
SH
chmod +x ~/.termux/boot/soak.sh
```

> 재부팅 자동 시작을 켜면 **구멍이 사라지는 게 아니라 짧아진다.** 판정은 여전히
> 로그의 구멍으로 하므로, 재부팅이 있었으면 그 흔적이 남는다. 그게 맞다 —
> 실제 운영에서도 재부팅 동안은 매매가 없다.

## 5. 사흘 뒤 판정

폰에서든 PC에서든(로그를 가져와서) 돌린다.

```bash
python scripts/phone_soak.py --report
```

```
틱        : 4320개
구간      : 09-06 20:00 ~ 09-09 20:00 KST
커버      : 72.0시간 (요구 72시간)
구멍      : 0개  가장 긴 것 0초

판정: 통과 — 폰이 상주 프로세스를 끊지 않았다. 3단계로 간다.
```

판정 규칙은 `src/soak.py`에 있고 테스트로 고정돼 있다:

- **구멍 = 틱 간격이 기대치의 1.5배를 넘는 구간.** 2.0배로 두면 안 된다 —
  틱 하나가 통째로 빠지면 간격이 정확히 2배가 되는데, 그게 이 게이트가 잡아야 할
  가장 작은 고장이다.
- **구멍 0개 + 요구 시간 충족** 둘 다여야 통과다. 한 시간만 촘촘히 돈 로그를
  통과시키면 게이트가 아무것도 안 막는다.
- **빈 로그는 미통과다.** '구멍 없음'으로 읽으면 안 돌린 것이 통과가 된다.

## 6. 그다음

| 판정 | 다음 |
|---|---|
| 통과 | 3단계 — 그림자 운전(같은 루프, **주문만 차단**). 옛 경로와 결정 불일치 0인 거래일 5일 |
| 미통과 | GCP `e2-micro`로 전환. 구멍의 시각을 보고 원인(재부팅·킬·네트워크)을 먼저 적어 둔다 |

미통과라고 실패가 아니다 — **돈을 걸기 전에 알아낸 것이 이 단계의 산출물이다.**

---

# 3단계 — 그림자 운전

2단계(3일 소크)를 2026-09-09에 통과했다. 여기서 하는 일은 하나다:

> **폰이 옛 경로와 같은 결정을 내리는가?**

폰은 **읽기만** 한다. 두 경로가 같은 계좌를 보고 있으므로 폰이 무엇이든 실행하면
그건 시험이 아니라 **중복 실행**이다. 막는 장치는 `src/trade/shadow.py`에 있고
층이 둘이다 — 층1은 `STOCKBOT_RUNNER=phone`이면 코드가 무조건 그림자로 판정하는 것,
층2는 **폰에 `WEBHOOK_SECRET`을 주지 않는 것**이다. 층1만 두면 플래그 실수로
실주문이 나가고, 층2만 두면 취소 경로(KIS 직접 호출, Vercel 우회)가 열려 있다.

## 3-1. 의존성 — **여기가 폰 워커의 진짜 첫 관문이다**

2단계는 표준 라이브러리만 썼다. 3단계는 아니고, 그 차이가 생각보다 크다.

```bash
cd ~/stockbot && git pull
pip install -r scripts/requirements-trade.txt
```

스크래퍼 requirements를 쓰지 마라 — pandas·sklearn까지 깔린다. 폰에서는 설치
시간보다 저장공간·메모리가 문제다.

### pydantic이 막는다 (2026-09-16 실측)

`pydantic` 2.x는 `pydantic-core`가 **Rust로 짜여 있고 PyPI에 aarch64-android
휠이 없다.** 소스 빌드로 넘어가고, 거기서 벽이 셋 연달아 선다.

**피할 수 없다** — `trade_engine.py` → `src/data/schemas.py`가 pydantic을 쓴다.
v1으로 낮추는 것도 안 된다(`field_validator`·`model_validator`는 v2 API다).
"폰에서만 import를 빼는" 우회는 **그림자 운전의 목적 자체를 깬다** — 같은 코드가
같은 결정을 내리는지 보는 단계인데 코드가 갈리면 비교가 무의미하다.

벽 셋과 그 답:

| 에러 | 뜻 | 답 |
|---|---|---|
| `Rust not found, installing into a temporary directory` | Rust가 없다 | `pkg install rust binutils` |
| `Target triple not supported by rustup: aarch64-unknown-linux-android` | maturin이 계산한 트리플과 Termux Rust(`aarch64-linux-android`)가 다르다 | `export CARGO_BUILD_TARGET=aarch64-linux-android` |
| `Failed to determine Android API level` | maturin이 기기 API 레벨을 못 읽는다 | `export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)` |

한 번에 쓰면:

```bash
pkg install rust binutils
pip install maturin
export CARGO_BUILD_TARGET=aarch64-linux-android
export ANDROID_API_LEVEL=$(getprop ro.build.version.sdk)   # 추측하지 말고 기기에서 읽는다
termux-wake-lock                                            # 빌드 중 화면이 꺼져도 안 멈추게
pip install --no-build-isolation pydantic==2.12.5
pip install -r scripts/requirements-trade.txt
```

`--no-build-isolation`이 필요한 이유: pip가 빌드용 새 환경을 만들면 방금 깐
maturin·Rust를 못 본다. 실제 컴파일이라 **10~30분** 걸린다.
env 세 개는 **빌드에만** 필요하다 — 루프 실행에는 필요 없다.

### 여기서 멈출지 판단하라

이 절차를 다 따라와서 성공했다면 좋다. 다만 **이건 pydantic 하나로 끝나지 않는다**
— 매매 경로에 네이티브 의존성이 하나 늘 때마다 같은 벽이 선다.

이 문서 앞머리의 기준을 다시 읽을 것:

> 월 ₩400~2,000을 아끼려고 돈 경로를 불안정한 런타임에 올릴 이유가 없다.
> **이 판단을 미리 정해 두는 것이 이 단계의 요점이다** — 나중에 "거의 됐는데"로
> 넘어가지 않기 위해서.

GCP `e2-micro`는 `linux-gnu`라 PyPI 휠이 그냥 맞고 이 문제가 애초에 안 생긴다.
**다음 네이티브 의존성에서 또 서면 그때는 전환하는 것이 이 계획의 원래 약속이다.**

⚠ 2026-09-16 실측 기기는 **CPython 3.14**였다. 최신 런타임일수록 휠이 없을
확률이 높다 — Termux python을 굳이 최신으로 올리지 않는 편이 낫다.

## 3-2. 환경변수 — **안 주는 것이 핵심이다**

`~/.stockbot_env`를 만든다 (`chmod 600`):

```bash
cat > ~/.stockbot_env <<'ENV'
export STOCKBOT_RUNNER=phone        # ← 이게 없으면 3단계가 성립하지 않는다
export TZ=Asia/Seoul
export PYTHONPATH=$HOME/stockbot
export KIS_APP_KEY=...
export KIS_APP_SECRET=...
export KIS_ACCOUNT_NO=...
export KIS_APP_ACCOUNT=...          # KIS_ACCOUNT_NO와 같은 값
ENV
chmod 600 ~/.stockbot_env
```

**주지 않는 것과 그 이유:**

| 변수 | 왜 안 주나 | 안 주면 어떻게 되나 |
|---|---|---|
| `WEBHOOK_SECRET` | 층2 방어. 신규 주문(`/api/trade/order`)과 미체결 취소의 열쇠다 | 주문 경로가 애초에 닫힌다 |
| `GH_PAT` | 비공개 레포(원장) 쓰기 권한이다. 폰이 원장을 건드리면 그림자가 아니다 | `[Program] GH 토큰 없음 → 원장 조회 불가 (fail-closed)` — 프로그램 경로가 안전하게 건너뛰어진다 |
| `TELEGRAM_BOT_TOKEN` / `CHAT_ID` | 폰과 Actions가 같은 장애를 두 번 알린다 | `send_alert`가 예외를 삼키고 로그만 남긴다 |
| `DASHBOARD_URL` | 주문을 내는 Vercel 엔드포인트 주소다 | 그림자에서는 쓸 일이 없다 |

> **`STOCKBOT_RUNNER=phone`을 빠뜨리는 것이 이 단계의 유일한 치명적 실수다.**
> 그러면 결정이 `actions`로 기록돼 **자기 자신과 비교**되고 불일치가 영원히 0으로
> 나온다. 통과처럼 보이는 실패다. 3-5의 첫 확인이 정확히 이걸 잡는다.

**한계(적어 두고 넘어간다)**: `GH_PAT`을 안 주므로 폰은 **프로그램(실계좌) 판단
경로를 돌지 않는다.** 이 단계가 비교하는 것은 **페이퍼 심의 판단**이다. 실계좌
판단까지 대조하려면 비공개 레포 **읽기 전용** 파인그레인드 토큰을 따로 발급해
`GH_PAT`에 넣어야 한다 — 그러면 `shadow.py`가 주문만 막고 원장은 읽는다.
4단계(소유권 이전) 전에 그 대조가 필요한지는 별도 판단이다.

## 3-3. 입력을 옛 경로와 맞춘다

폰이 다른 시세를 보면 판단이 갈려도 그건 불일치가 아니라 **입력 차이**다.
비교기가 그 둘을 나누지만(`input_hash`), 애초에 같은 상태에서 시작해야 한다.

```bash
cd ~/stockbot
git fetch origin db-data:db-data          # 토큰 불필요 — public 레포다
git checkout db-data -- data/
```

**폰은 db-data에 push하지 않는다.** Actions 쪽 writer와 다투면 lost update가
난다. `scripts/trade_loop.py` 자체는 배포를 하지 않으므로(배포는 워크플로의
별 스텝이다) 그냥 안 하면 된다.

## 3-4. 루프 시작

```bash
cat > ~/.termux/boot/shadow.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
. $HOME/.stockbot_env
cd $HOME/stockbot
while :; do
  git fetch -q origin db-data:db-data 2>/dev/null
  git checkout -q db-data -- data/ 2>/dev/null
  python -u scripts/trade_loop.py >> $HOME/shadow.log 2>&1
  sleep 60
done
SH
chmod +x ~/.termux/boot/shadow.sh
```

`trade_loop.py`는 한 번 호출에 **두 바퀴**(60초 간격)를 돌고 예산(85초)을 쓰면
끝난다. 그래서 바깥 `sleep 60`과 합쳐 옛 경로(태스커 2분 트리거)와 비슷한 격자가
된다. 2단계 소크를 계속 돌리고 있었다면 그건 멈춰도 된다 — 이 루프가 같은 질문에
답한다.

## 3-5. 첫 확인 (루프 시작 직후, 5분 안에)

```bash
ls ~/stockbot/data/decisions_*_phone.csv
```

**이 파일이 생기지 않으면 더 진행하지 마라.** 둘 중 하나다.

1. `STOCKBOT_RUNNER`가 안 걸렸다 → `decisions_*_actions.csv`가 생긴다. 환경변수를 고친다.
2. 루프가 판단에 도달하지 못했다 → `~/shadow.log`에서 `[준비상태]`와 `깔때기`를 본다.

그리고 그림자가 실제로 걸렸는지:

```bash
grep -i "그림자\|shadow\|차단" ~/shadow.log | head
```

## 3-6. 스냅샷을 PC로 옮긴다

**전송을 자동화하지 않는다.** 폰이 스스로 올리려면 git PAT이나
`WEBHOOK_SECRET`이 필요한데, 둘 다 층2 방어를 뚫는다 — 3단계의 목적과 정면으로
어긋난다. 5거래일 게이트에는 수동 복사로 충분하다.

Tailscale이 이미 붙어 있으면(2단계 §3):

```bash
# PC에서
scp -P 8022 '<user>@<tailscale-ip>:~/stockbot/data/decisions_*_phone.csv' ./shadow_in/
```

기준선은 db-data에서 받는다. **러너 이름이 `actions`가 아니라
`actions-trading`이다**(`trading.yml`이 그렇게 띄운다):

```bash
git fetch origin db-data && git checkout origin/db-data -- data/
cp data/decisions_*_actions-trading.csv ./shadow_in/
```

## 3-7. 판정

```bash
python scripts/compare_shadow_decisions.py --date 20260917 --data-dir ./shadow_in
```

읽는 법:

- **판단 일치율** — `input_hash`가 같은 `(cycle_id, sim, code)`에서 decision이
  같은 비율. 이것만이 "같은 결정을 내렸나"의 답이다.
- **입력 불일치(`input_hash` 다름)** — 둘이 다른 시세를 봤다. 이게 비교 대상의
  대부분이면 **그림자 비교 자체가 성립하지 않는다** — 같은 입력을 본 순간이 없다.
  3-3의 상태 동기화나 폰의 시세 경로를 먼저 본다.
- **평가 미도달(`seen`)** — 조기종료로 판단에 도달하지 못한 행. 분모에서 빠진다.
  양쪽 다 `seen`인 쌍을 "일치"로 세면 아무도 판단하지 않은 행으로 100%가 만들어진다.
- **키 모호** — `cycle_id`가 빈 행. 폰이 `scripts/trade_loop.py` 경로를 타지 않으면
  번호가 안 붙어 조인이 무너진다. 이게 크면 3-4의 실행 명령을 확인한다.
- **비교 불가** — 종료코드 **2**다. 0이 아니다. 게이트로 쓸 때 0을 통과로 읽으면
  안 되기 때문이다.

## 3-8. 통과 기준과 그다음

2단계 문서의 표대로 **결정 불일치 0인 거래일 5일**이다. 임계값을 코드가 판정하지
않는 이유는, 그 기준이 아직 문서에만 있고 숫자로 고정된 적이 없어서다 —
비교기는 수치만 내고 판정은 사람이 한다.

| 판정 | 다음 |
|---|---|
| 5거래일 불일치 0 | 4단계 — `shadow.py`의 `_SHADOW_RUNNERS`에서 `'phone'`을 뺀다. **한 줄이고 리뷰에서 보인다.** 그 전에 실계좌 판단 경로도 대조할지 결정한다(3-2의 한계 참고) |
| 불일치 발생 | 불일치 행의 `sim`·`reason`을 보고 원인을 적는다. 입력 차이면 3-3, 판단 차이면 그 심의 코드 |
