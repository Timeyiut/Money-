# 債務儀表 FinGuard

個人負債、金流與預算的單一儀表板，做成可裝到 iOS 主畫面的 PWA。
所有試算都在裝置上完成，沒有後端，不上傳任何資料。

---

## 一次性設定

### 1. 建立 repo 並推上去

```bash
git init
git add .
git commit -m "FinGuard PWA"
git branch -M main
git remote add origin https://github.com/<你的帳號>/finguard.git
git push -u origin main
```

Repo 設成 **Public**（免費方案的 GitHub Pages 只支援公開 repo）。
裡面沒有任何個人識別資料，但貸款金額是真實的——若不想公開，需要 GitHub Pro。

### 2. 打開 Pages

Repo → **Settings** → **Pages** → Source 選 **GitHub Actions**（不是 Deploy from a branch）。

推上去後 Actions 會自動跑，約一分鐘。網址會是：

```
https://<你的帳號>.github.io/finguard/
```

### 3. 裝到 iPhone 主畫面

用 **Safari** 開上面的網址 → 分享鈕 → **加入主畫面**。

裝完會有自己的圖示、全螢幕、沒有網址列。第一次開啟後即可離線使用。

> 必須用 Safari 加入。其他瀏覽器加的捷徑不會套用 manifest，開起來仍是網頁樣子。

---

## 自動更新怎麼運作

之後你只要 `git push`，手機上的 App 就會自己更新，不用重裝。

機制分三層：

| 層 | 做什麼 |
|---|---|
| **CI** | `deploy.yml` 把 commit SHA 寫進 `sw.js` 的快取名稱和 `version.json`。每次 push 都是新的快取名，瀏覽器不可能繼續沿用舊版。 |
| **Service Worker** | 導覽請求走 network-first，有網路時新的 `index.html` 一定勝出；靜態檔走 stale-while-revalidate；字型另存在不隨版本清除的快取，避免更新時字體閃動。 |
| **頁面** | 每次回到前景、每小時、以及重新連上網路時各檢查一次。抓到新版**不會當場重整**，而是跳出提示；你可以立刻套用，不理它的話下次回到前景時自動套用。 |

不當場重整是刻意的——你可能正在輸入月收入或拖預算滑桿，畫面突然重載會很煩。

每頁最底下會顯示 `build xxxxxxx`，可以用它確認手機上跑的是哪一版。

### 手動強制更新

若要驗證更新流程：把 App 切到背景再切回來，提示應該會出現。
真的卡住的話，iOS：設定 → Safari → 清除瀏覽紀錄與網站資料，然後重開 App。

---

## 檔案結構

```
.
├── index.html                  # 整個 App（HTML/CSS/JS 單檔）
├── manifest.webmanifest        # PWA 設定：名稱、圖示、standalone
├── sw.js                       # Service worker，版本化快取
├── version.json                # CI 產生，供頁面顯示與比對版本
├── icons/                      # 180/192/512 + maskable
├── tools/make_icons.py         # 重新產生圖示用
├── tools/gmail_oauth_setup.py  # 一次性本機授權，換 Gmail refresh token
├── tools/fetch_bank_statements.py  # CI 用：抓信、解密 PDF、擷取金額
├── data/statements.json        # CI 產生，自動擷取的帳單記錄
├── .nojekyll                   # 讓 Pages 不要跑 Jekyll
└── .github/workflows/
    ├── static.yml
    └── fetch-bank-statements.yml   # 每月自動抓帳單信
```

---

## 本機預覽

Service worker 需要 HTTPS 或 localhost，直接開檔案（`file://`）不會生效。

```bash
python3 -m http.server 8000
# 開 http://localhost:8000
```

本機跑的時候版本會顯示 `dev`，因為佔位字串只有 CI 會替換。

---

## 改資料

貸款資料在 `index.html` 的 `LOANS` 陣列，就在 `<script>` 開頭。
改完 `git push`，手機上下次開啟就會是新的。

```js
const LOANS = [
  { id:'B', name:'分期信貸', bank:'…',
    balance:278486, rate:8.19, payment:3425, term:120, paid:2, … },
  …
];
```

`balance` 建議每月對帳日更新一次，其餘欄位只有在合約變動時才需要動。

---

## 自動抓信箱裡的月帳單（選用）

`.github/workflows/fetch-bank-statements.yml` 每月跑一次（可在 Actions 頁手動觸發），用 Gmail API 搜尋帳單信、下載 PDF 附件，遇到有密碼保護的檔案會用身分證字號／生日的常見組合嘗試解鎖，讀出金額後寫進 `data/statements.json`。首頁「負債」分頁會多一塊「信箱自動擷取的帳單」卡片顯示這些資料，**但不會自動覆蓋 `LOANS` 陣列**——金額對不對還是要你自己看過才手動改，避免抓錯或解析錯誤直接污染你的帳。

這個功能完全不影響本工具「無後端、不上傳資料」的原則：解密只發生在 GitHub 自己的 Actions 執行環境裡，PDF 原始內容和解密後全文都不會寫進 repo，只有比對用的日期/主旨/金額幾個欄位會進 `data/statements.json`。

### 設定步驟

1. **建立 Gmail API 用戶端**：到 [Google Cloud Console](https://console.cloud.google.com/apis/credentials) 建一個 OAuth Client ID（類型選「桌面應用程式」），拿到 `Client ID` 和 `Client Secret`。
2. **在自己的電腦上**（不是 CI）跑一次授權，拿 refresh token：
   ```bash
   pip install -r tools/requirements.txt
   python3 tools/gmail_oauth_setup.py --client-id "..." --client-secret "..."
   ```
   會開瀏覽器登入你的 Gmail 並要求唯讀權限，完成後終端機會印出 refresh token。
3. **在 repo 加 Secrets**（Settings → Secrets and variables → Actions）：

   | Secret | 說明 |
   |---|---|
   | `GMAIL_CLIENT_ID` | 步驟 1 拿到的 Client ID |
   | `GMAIL_CLIENT_SECRET` | 步驟 1 拿到的 Client Secret |
   | `GMAIL_REFRESH_TOKEN` | 步驟 2 印出的 refresh token |
   | `BANK_ID_NUMBER` | 身分證字號，例如 `A123456789` |
   | `BANK_BIRTHDAY` | 生日，`MM-DD` 即可（例如 `06-25`），不用填年份——目前信箱裡所有銀行的密碼規則都用不到出生年。要填完整 `YYYY-MM-DD` 也可以，程式會多嘗試幾組含年份的組合當後備。 |

4. 存完 secrets 後到 Actions 頁手動跑一次 `Fetch bank e-statements` 確認能正常抓到、解密成功。

### 密碼規則涵蓋範圍

腳本會依序嘗試多組密碼，涵蓋這個信箱實際會收到的帳單信（規則寫在各家信件內文）：

| 寄件銀行 | PDF 開啟密碼 |
|---|---|
| 華南銀行／華南永昌證券／華南期貨 | 身分證字號（大寫） |
| 永豐銀行（綜合對帳單、信用卡） | 身分證字號（大寫） |
| 國泰綜合證券 | 身分證字號（大寫） |
| 王道銀行 O-Bank | 身分證字號（大寫） |
| 臺灣土地銀行 | 身分證字號（大寫） |
| 兆豐銀行 | 身分證字號（大寫） |
| 台新銀行信用卡 | 身分證字號後 2 碼 + 生日 MMDD |
| 星展銀行信用卡 | 身分證字號後 4 碼 + 生日 MMDD |

> 注意：目前信箱裡**沒有**中國信託的帳單信，而 `LOANS` 裡的兩筆主要貸款（3362／3375）都在中國信託。也就是說這個自動化目前抓得到各家對帳單和信用卡帳單，但抓不到你最大那兩筆貸款的餘額——那部分仍需手動更新，或另外去中國信託開通電子帳單寄送到這個信箱。

> 身分證字號和生日只存在 GitHub Actions 的加密 secrets 裡，永遠不會出現在程式碼、commit 或 `data/statements.json` 裡。如果不想用這個功能，不加這些 secrets 即可——workflow 沒有 secrets 會直接失敗，不影響其他功能。

## 待辦

- [ ] 接上信用卡消費明細 CSV，補上「每月必要 / 臨時 / 分期」三類支出
- [ ] 把卡片分期併入還款瀑布（目前只有四筆銀行貸款）
- [ ] 其他貸款 2027/03 到期尾款金額，待跟銀行確認
- [ ] 依各家銀行 PDF 實際格式調整 `tools/fetch_bank_statements.py` 的金額擷取規則（目前是通用關鍵字比對）

---

本工具做的是數學，不是理財建議。
