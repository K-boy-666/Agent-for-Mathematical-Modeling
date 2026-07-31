# Math Modeling MCP锛氳璁°€佽鍒掍笌瀹炴柦鐘舵€佹€昏

> 鏇存柊鏃ユ湡锛?026-07-31
> 褰撳墠鍒嗘敮锛歚codex/m1a`
> 褰撳墠宸叉彁浜ゅ熀绾匡細`7719f2937d640ec90bc8b96cf8b1a6d007b3e459`
> 鐘舵€佸彛寰勶細鍙湁宸茬粡鎻愪氦銆侀€氳繃瑙勫畾娴嬭瘯骞跺畬鎴愮嫭绔嬪鏌ョ殑浠诲姟鎵嶆爣璁颁负鈥滃畬鎴愨€濄€?
## 1. Phase 0 璁捐

Phase 0 鐨勬潈濞佽璁℃枃妗ｆ槸
[2026-07-16-math-modeling-mcp-design.md](superpowers/specs/2026-07-16-math-modeling-mcp-design.md)銆?
### 1.1 浜у搧瀹氫綅

鏈」鐩笉鏄竴涓緷闈犻暱鎻愮ず璇嶇洿鎺ョ敓鎴愬浗璧涜鏂囩殑鑱婂ぉ鏈哄櫒浜猴紝鑰屾槸锛?
> 涓€涓湰鍦拌繍琛屻€佸涓绘棤鍏炽€佸彲鎵╁睍銆佸彲楠岃瘉銆佸彲杩芥函鐨勬暟瀛﹀缓妯¤绠楁牳蹇冦€?
Codex 鏄涓€涓涓汇€傚悗缁?Claude Code銆乀RAE 绛夊涓婚€氳繃钖勯€傞厤灞傝繛鎺ュ悓涓€鏍稿績锛?涓嶉噸澶嶅疄鐜版暟瀛︽眰瑙ｃ€侀」鐩姸鎬併€佸疄楠岃褰曞拰楠岃瘉閫昏緫銆?
```text
Codex / Claude Code / TRAE
             鈫?        瀹夸富钖勯€傞厤灞?             鈫?      鏈湴 STDIO MCP
             鈫?     Application Facade
             鈫?绋冲畾鏍稿績 + 鑳藉姏娉ㄥ唽琛?+ 楠岃瘉鍣?             鈫? SQLite / 鍒跺搧 / 鏁板€兼墽琛岀幆澧?```

### 1.2 鏍稿績鏋舵瀯鍐崇瓥

- 閲囩敤鍗曚粨搴撱€佸崟 Python 鍙戣鐗╃殑妯″潡鍖栧崟浣擄紝涓嶅湪 M1 鎻愬墠寮曞叆寰湇鍔°€?- `modeling_core` 涓嶄緷璧?MCP銆丼QLite銆丆odex 鎴栦换浣曞叿浣撴暟瀛﹁兘鍔涖€?- MCP 灞傚彧瀹屾垚鍗忚杞崲锛屼笉瀹炵幇鏁板绠楁硶鎴栫洿鎺ヨ闂?SQLite銆?- 鏁板鑳藉姏浠ユ樉寮忔敞鍐岀殑 **Built-in Capability** 鎻愪緵锛涙湭鏉ュ彲瀹夎鐨勭涓夋柟鍗曞厓鎵嶇О涓?  **External Plugin**銆?- 鎵€鏈夋暟鍊肩粨璁哄繀椤绘潵鑷湡瀹炵▼搴忔墽琛岋紝涓嶈兘鐢卞ぇ妯″瀷鍦ㄦ枃瀛椾腑鐢熸垚銆?- 姹傝В鍣ㄤ笌楠岃瘉鍣ㄧ浉浜掔嫭绔嬶紱楠岃瘉鍣ㄤ笉鑳藉鐢ㄦ眰瑙ｅ櫒鐨勬悳绱㈡垨鏁板€煎垽瀹氬疄鐜般€?- 椤圭洰銆丒xperiment銆丄ttempt銆丷esultSnapshot銆乂alidation 鍜屾姤鍛婂舰鎴愬彲鏌ヨ鐨勬函婧愰摼銆?- 鍐欐搷浣滈噰鐢?`operation_id + canonical_request_hash` 瀹炵幇骞傜瓑锛涙暟瀛︽墽琛屾湡闂翠笉淇濇寔闀?  SQLite 浜嬪姟銆?- 鍘熷璧涢闄勪欢鍙锛涚敓鎴愭暟鎹€佺粨鏋滃拰鎶ュ憡蹇呴』鐗堟湰鍖栧苟鍙拷婧€?- M2.5 鍦?ODE銆佷紭鍖栫瓑閲嶈绠楄兘鍔涘墠寮曞叆鐭敓鍛藉懆鏈?worker 鍜岀‖瓒呮椂銆?
### 1.3 M1 鐨勫叚涓叕鍏卞伐鍏?
M1 瀵瑰涓诲彧鏆撮湶浠ヤ笅鍏釜宸ュ叿锛?
```text
health_check
create_project
get_project_status
list_capabilities
run_experiment
validate_experiment
```

鍐呴儴姹傝В鍣ㄣ€丼QLite 琛ㄣ€佽〃杈惧紡瑙ｆ瀽鍣ㄥ拰楠岃瘉鍣ㄩ兘涓嶆槸瀹夸富鍙互浠绘剰璋冪敤鐨勫叕鍏卞伐鍏枫€?
### 1.4 鐘舵€佷笌鍙俊鎬фā鍨?
- Project锛歚UNINITIALIZED 鈫?STORAGE_READY 鈫?READY`锛屽畬鏁存€у紓甯歌繘鍏?  `DEGRADED`銆?- Attempt锛?  `PENDING 鈫?RUNNING 鈫?SUCCEEDED | NUMERICAL_FAILURE | ERRORED | TIMED_OUT | ABANDONED`銆?- Validation锛?  `PENDING 鈫?RUNNING 鈫?SUCCEEDED | ERRORED | TIMED_OUT | ABANDONED`銆?- Validation 鐨勮繍琛岀姸鎬佷笌鏁板缁撹鍒嗙锛涘彧鏈夎繍琛屾垚鍔熷悗鎵嶆湁
  `PASSED | FAILED | INCONCLUSIVE`銆?- `NUMERICAL_FAILURE` 鏄甯告暟瀛︾粨鏋滐紝渚嬪鍖洪棿鍐呮棤绗﹀彿鍙樺寲锛涘畠涓嶆槸绯荤粺閿欒銆?- 缁撴灉銆佽緭鍏ャ€佹ā鍨嬨€佹暟鎹揩鐓у拰楠岃瘉鎶ュ憡鍧囦娇鐢ㄨ鑼?JSON 涓?SHA-256 褰㈡垚璇佹嵁閾俱€?
### 1.5 Context Engineering

涓婁笅鏂囬噰鐢ㄦ笎杩涘紡鍔犺浇锛?
```text
鏍?AGENTS.md
鈫?鏈€杩戠洰褰曠殑宓屽 AGENTS.md
鈫?docs/context/index.md
鈫?涓庡綋鍓嶄换鍔℃湁鍏崇殑鏋舵瀯銆佸绾﹀拰 ADR
鈫?浠呭湪闇€瑕佹椂鍔犺浇瀵瑰簲 Skill 鍜屾暟瀛︾煡璇?```

闀挎湡瑙勫垯杩涘叆 `AGENTS.md`锛屾潈濞佷骇鍝佸拰鏋舵瀯鐭ヨ瘑杩涘叆 `docs/`锛岀▼搴忔€у伐浣滄祦杩涘叆
Skills锛屽綋鍓嶅閲忕洰鏍囪繘鍏ヤ换鍔?Prompt銆侽DE銆丳DE銆佺粺璁°€佷紭鍖栫瓑鐭ヨ瘑涓嶄細甯搁┗姣忔
寮€鍙戜笂涓嬫枃銆?
### 1.6 Harness Engineering

- 鎻愪緵鍗曚竴楠岃瘉鍏ュ彛锛歚modeling verify --milestone <milestone>`銆?- 娴嬭瘯鍒嗕负鍗曞厓銆佸绾︺€佹灦鏋勩€佹暟瀛︺€侀泦鎴愩€佸鐜般€佸畨鍏ㄣ€侀獙鏀跺拰鐪熷疄 STDIO 榛勯噾閾捐矾銆?- 鏋舵瀯娴嬭瘯闃绘鏍稿績鍙嶅悜渚濊禆閫傞厤鍣ㄣ€佹暟鎹簱鎴栧叿浣撹兘鍔涖€?- 鏁板鍙樺舰娴嬭瘯鐢ㄤ簬楠岃瘉骞崇Щ銆佺缉鏀俱€佺鍙风炕杞€佸崟浣嶅彉鎹㈢瓑涓嶅彉閲忋€?- 瀹屾垚澹版槑蹇呴』鍖呭惈鐪熷疄鍛戒护銆佹祴璇曠粺璁°€丟it diff銆佸畬鏁?commit hash 鍜屽凡鐭ュ亸宸€?- M1b 澧炲姞鏁呴殰娉ㄥ叆銆佸唴瀹瑰鍧€鍒跺搧銆佽法骞冲彴楠岃瘉鍜屽穿婧冩仮澶嶈瘉鎹€?
### 1.7 Phase 0 鏄庣‘涓嶅仛

M1 涓嶅寘鍚畬鏁磋禌棰樿嚜鍔ㄧ悊瑙ｃ€佸叏棰樿嚜涓绘ā鍨嬮€夋嫨銆佽鏂囪嚜鍔ㄧ敓鎴愩€乄eb UI銆佸鐢ㄦ埛鏈嶅姟銆?External Plugin 甯傚満銆佷换鍔￠槦鍒椼€亀orker 姹犳垨鎵€鏈夊巻骞撮姹傝В銆傚畠棣栧厛寤虹珛涓€涓彲淇°€?鍙墿灞曠殑璁＄畻涓庨獙璇佺旱鍚戝垏鐗囥€?
## 2. M1 瀹炴柦璁″垝

M1 鐨勬潈濞佸疄鏂借鍒掓槸
[2026-07-17-math-modeling-mcp-m1.md](superpowers/plans/2026-07-17-math-modeling-mcp-m1.md)銆?
褰撳墠缁忔壒鍑嗙殑鎬昏矾绾夸负锛?
```text
M1a-0R 瀹夸富璇佹嵁淇闂?鈫?M1a A1鈥揂12 鍔熻兘绾靛悜鍒囩墖
鈫?C1 鐪熷疄鍥借禌灏忛棶浜у搧楠岃瘉
鈫?M1b B1鈥揃12 鍙俊鍖栧姞鍥?```

杩欎竴璺嚎鎶?C1 鏀惧湪瀹屾暣 M1b 涔嬪墠锛岀敤鐪熷疄鍥借禌灏忛棶妫€楠屽钩鍙版槸鍚﹀叿鏈変骇鍝佷环鍊硷紱C1
浠嶅繀椤荤瓑寰?M1a Hard Gate 閫氳繃銆?
### 2.1 M1a-0R锛氬涓诲彲琛屾€ч棬

鐩爣鏄瘉鏄庢寮?Codex 瀹夸富鑳藉閫氳繃鐪熷疄 STDIO MCP 璋冪敤涓€娆?`root_finding`锛岃€屼笉鏄緷闈?shell銆佹墜鍐?JSON 鎴栨ā鍨嬭嚜杩般€傝闂ㄥ凡缁忓畬鎴愩€?
### 2.2 M1a锛氬姛鑳界旱鍚戝垏鐗?
| 浠诲姟 | 浜や粯鍐呭 | 褰撳墠鐘舵€?|
|---|---|---|
| A1 | 閿佸畾 Python/uv 椤圭洰涓庨獙璇佸叆鍙?| 瀹屾垚 |
| A2 | 涓ユ牸 0.1 宸ュ叿銆侀敊璇笌绋冲畾鍝堝笇濂戠害 | 瀹屾垚 |
| A3 | 棰嗗煙涓嶅彉閲忋€佺鍙ｄ笌 Application Facade | 瀹屾垚 |
| A4 | 鍘熷瓙瀛樺偍 bootstrap 涓?SQLite schema 1 | 瀹屾垚 |
| A5 | 灏佸瓨鐨?Built-in Capability 娉ㄥ唽琛?| 瀹屾垚 |
| A6 | 瀹夊叏 math-expr-v1 涓庤鑼冩眰鏍硅緭鍏?| 瀹屾垚 |
| A7 | 纭畾鎬т簩鍒嗘硶姹傛牴鑳藉姏 | 瀹屾垚 |
| A8 | 鐙珛娈嬪樊楠岃瘉鍣?| 瀹屾垚 |
| A9a | A9 鎵€闇€鐨勬渶灏忓瓨鍌?寮傚父濂戠害淇 | 杩涜涓紝灏氭湭鎻愪氦 |
| A9b | Facade銆丼QLite銆佸箓绛夊拰瀹屾暣瀹為獙/楠岃瘉缂栨帓 | 鏈紑濮?|
| A10 | 涓ユ牸浣庡眰 STDIO MCP 鍏伐鍏烽€傞厤 | 鏈紑濮?|
| A11 | 鐪熷疄 STDIO 榛勯噾閾捐矾涓?M1a Harness | 鏈紑濮?|
| A12 | doctor銆佸熀纭€涓婁笅鏂囥€丆odex 妯℃澘涓庨獙鏀堕棬 | 鏈紑濮?|

A9a 鏄?A9 鍐呴儴鐨?enabling slice锛屼笉澧炲姞绗?13 涓《灞備换鍔°€傚畠鐢ㄤ簬闃叉
Application 灞傚鍏ュ叿浣撴眰鏍瑰紓甯革紝骞朵娇瀛樺偍绔彛鑳藉師瀛愪繚瀛樿鑼冨寲鍚庣殑棰嗗煙瀵硅薄銆?
### 2.3 M1a Hard Gate

M1a 鍙湁鍦ㄤ互涓嬪懡浠ら€€鍑虹爜涓?0銆佸繀闇€璺宠繃涓?0 鏃舵墠瀹屾垚锛?
```powershell
uv run --locked --no-sync modeling verify --milestone m1a
```

璇ラ棬蹇呴』璇佹槑鐪熷疄 STDIO 鍏伐鍏烽摼璺€侀粍閲戞眰鏍瑰疄楠屻€佺嫭绔嬮獙璇併€丼QLite 婧簮銆佸箓绛夈€?瓒呮椂銆佸畨鍏ㄨ竟鐣屻€丆ontext 鏂囨。鍜岄獙璇佽瘉鎹兘瀛樺湪銆?
### 2.4 M1b锛氬彲淇″寲鍔犲浐

M1b 璁″垝淇濈暀锛屼絾鎸夋壒鍑嗚矾绾垮湪 C1 涔嬪悗缁х画锛?
| 浠诲姟 | 璁″垝鍐呭 |
|---|---|
| B1 | 灏嗗凡璇佹槑鐨?0.x 鍒囩墖鏅嬪崌涓虹ǔ瀹?1.0 濂戠害 |
| B2 | 瀹屾暣 RFC 8785 鍚戦噺涓?Schema 鍏煎鍩虹嚎 |
| B3 | 甯︽姢鏍忕殑 Built-in Capability 鑴氭墜鏋?|
| B4 | SQLite schema 2 涓庡唴瀹瑰鍧€ ArtifactStore |
| B5 | 杈撳叆/鐜蹇収鍜岀粨鏋?鎶ュ憡鍒跺搧鍙戝竷 |
| B6 | 瀹屾暣骞傜瓑鎭㈠銆侀噸鍚敹鏁涘拰 rerun |
| B7 | 浜斾釜宕╂簝绐楀彛鏁呴殰娉ㄥ叆涓庢枃浠剁郴缁熷畨鍏?|
| B8 | 娣卞寲 doctor 涓庢暟瀛?閲嶅惎澶嶇幇 |
| B9 | 娓愯繘寮忎笂涓嬫枃璺敱鍜岃兘鍔?Skills |
| B10 | 绋冲畾鏋舵瀯銆佸绾︺€佽繍缁村拰 ADR 鏂囨。 |
| B11 | Windows/Ubuntu 涓€鑷寸殑 M1b 楠岃瘉瓒呴泦 |
| B12 | 瀹屾垚璇佹嵁鍖呬笌 Codex 瀹夸富榛勯噾閾捐矾 |

## 3. C1 璁″垝

C1 鐨勬潈濞佽璁′笌瀹炴柦鏂囦欢鏄細

- [C1 璁捐瑙勬牸](superpowers/specs/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice-design.md)
- [C1 瀹炴柦璁″垝](superpowers/plans/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice.md)

### 3.1 C1 鐨勭洰鏍?
C1 閫夌敤 2022 骞村叏鍥藉ぇ瀛︾敓鏁板寤烘ā绔炶禌 A 棰橀棶棰樹竴锛屽缓绔嬬涓€涓湡瀹為棴鐜細

```text
瀹樻柟棰橀潰鍜岄檮浠?鈫?鍙鍐呭瀵诲潃璧勪骇
鈫?Codex 鐢熸垚 MMIR
鈫?鐢ㄦ埛纭鍏蜂綋 revision
鈫?涓や釜闃诲凹鎯呭舰鍒嗗埆鎵ц
鈫?涓ゅ鐙珛鏁板€奸獙璇?鈫?Excel銆佸浘銆佺粨鏋滃崱鍜?provenance
鈫?鐪熷疄 Codex MCP 绔埌绔瘉鎹?```

C1 鏄?`0.x product-validation preview`锛屼笉瀹ｇО閫氱敤璧涢宸ヤ綔娴併€佸畬鏁?M1b 鎴栬法骞冲彴
绋冲畾鍙戝竷宸茬粡瀹屾垚銆?
### 3.2 鏁板鑳藉姏

鑳藉姏 ID锛?
```text
dynamics.coupled_heave/0.1.0
```

瀹冩眰瑙ｆ诞瀛愪笌鎸瓙鐨勮€﹀悎鍨傝崱鏂圭▼锛屽苟鍒嗗埆澶勭悊锛?
```text
linear:    D(q) = 10000 q
power_law: D(q) = 10000 |q|^0.5 q
```

鐢熶骇姹傝В浣跨敤 DOP853锛宍rtol=1e-9`銆乣atol=1e-11`锛岃緭鍑哄浐瀹氫负
`t_i=0.2i, i=0鈥?97`锛屽叡 898 琛岋紝缁堢偣 179.4 绉掋€?
绾挎€ф儏褰㈢敱澧炲箍鐘舵€佺煩闃垫寚鏁拌В鐙珛楠岃瘉锛涢潪绾挎€ф儏褰㈢敱姝ラ暱 0.01 绉掑拰 0.005 绉掔殑
鍥哄畾姝ラ暱 RK4 鐙珛楠岃瘉銆傜敓浜цВ涓庡弬鑰冭В瑕佹眰 `rtol=2e-4`銆乣atol=2e-6`锛屽綊涓€鍖?鑳介噺闂悎璇樊涓嶈秴杩?`1e-3`銆?
### 3.3 C1 鐨勫叓涓疄鏂戒换鍔?
| 浠诲姟 | 浜や粯鍐呭 | 褰撳墠鐘舵€?|
|---|---|---|
| C1.1 | 鍥涗釜棰勮宸ュ叿濂戠害鍜岀ǔ瀹氶敊璇?| 鏈紑濮?|
| C1.2 | 鍙銆佸唴瀹瑰鍧€鐨勫畼鏂硅祫浜у揩鐓?| 鏈紑濮?|
| C1.3 | 甯?revision 鍜屼汉宸ョ‘璁ょ殑鏈€灏?MMIR | 鏈紑濮?|
| C1.4 | 60 绉掔‖瓒呮椂銆?6 MiB 涓婇檺鐨勭煭鐢熷懡鍛ㄦ湡 worker | 鏈紑濮?|
| C1.5 | `dynamics.coupled_heave` DOP853 鐢熶骇姹傝В | 鏈紑濮?|
| C1.6 | 鐭╅樀鎸囨暟銆丷K4 鍜岃兘閲忛棴鍚堢嫭绔嬮獙璇?| 鏈紑濮?|
| C1.7 | 涓や唤 Excel銆佹椂搴忓浘銆佺粨鏋滃崱鍜?provenance | 鏈紑濮?|
| C1.8 | `verify --milestone c1` 涓庣湡瀹?Codex 瀹夸富闂?| 鏈紑濮?|

### 3.4 C1 杈撳嚭

- `result1-1.xlsx`
- `result1-2.xlsx`
- 涓ょ闃诲凹鎯呭舰鐨勬椂搴忓浘
- 10銆?0銆?0銆?0銆?00 绉掔粨鏋滃崱
- 鍙傛暟銆佸崟浣嶃€佹潵婧愩€佸亣璁俱€佷唬鐮佺増鏈€佽繍琛屽拰楠岃瘉 provenance

鍙湁涓や釜 Attempt 閮藉叿鏈?`PASSED` Validation 鏃讹紝`export_subproblem` 鎵嶈兘鍙戝竷
鏈€缁堝埗鍝併€?
### 3.5 C1 Hard Gate

```powershell
uv run --locked --no-sync modeling verify --milestone c1
```

瑕佹眰閫€鍑虹爜 0銆佸繀闇€璺宠繃 0銆佷袱涓?Validation 鍧囦负 `PASSED`锛屼笖鐪熷疄 Codex 瀹夸富鍙粡
MCP 瀹屾垚寤洪」銆佽祫浜х櫥璁般€丮MIR 鑽夋嫙/纭銆佷袱娆¤繍琛屻€佷袱娆￠獙璇佸拰涓€娆″鍑恒€?
## 4. 宸插畬鎴愪换鍔″拰鎻愪氦璁板綍

浠ヤ笅璁板綍鏉ヨ嚜褰撳墠浠撳簱 Git 鍘嗗彶涓?SDD progress ledger銆?
| 闃舵/浠诲姟 | 鎻愪氦 | 璇存槑 | 瀹℃煡鐘舵€?|
|---|---|---|---|
| M1a-0R | `d3fb4c126e8b81b2f74bab31d80e7b4a7313cdae` | `spike: prove Codex-hosted MCP root-finding round trip` | 宸插畬鎴?|
| M1a-0R 淇 | `610c23869452cbd9e5801e7ff44cdd58cb5d3c22` | `fix: close M1a-0R evidence gate gaps` | 鐙珛瀹℃煡閫氳繃 |
| A1 | `fe0018314c98dcb523df6369344d0cf5946a42b4` | `build: establish locked Python project` | 鐙珛瀹℃煡閫氳繃 |
| A2 | `2c5c37f76a331211dd53dcc7075369f43432be14` | `feat: define strict M1a public contracts` | 鍚庣画淇 |
| A2 淇 1 | `26f33ae606677166f7f30a9a75c2b263e850f82f` | `fix: enforce strict M1a contract invariants` | 鍚庣画淇 |
| A2 淇 2 | `456551a27adde5cbab38b4b8a08ccf6fa08b2d47` | `fix: constrain M1a validation trace policy` | 鐙珛瀹℃煡閫氳繃 |
| A3 | `9f30b904ddfae89caed9c2b3a8c5dbbc5c4f1ff7` | `feat: define host-independent core boundaries` | 鍚庣画淇 |
| A3 淇 | `14c0a45353885ea36c59a01e885d393b4fc8d421` | `fix: enforce validated A3 domain contracts` | 鐙珛瀹℃煡閫氳繃 |
| A4 璁″垝淇 | `fcb7358c73ee39ccbf8ed73534c61198b8e47dfc` | `docs: correct A4 package ownership` | 鐙珛瀹℃煡閫氳繃 |
| A4 | `878acf1058bea4e46e4168c000a5ac97a904d55a` | `feat: add atomic SQLite project storage` | 鍚庣画淇 |
| A4 淇 | `670e8e00232b9d34edace9270f96b597ce5e386a` | `fix: reject reparse ancestors in project paths` | 鐙珛瀹℃煡閫氳繃 |
| A5 | `0b5ca4c6d9801a9f5f459c2a4403fabc662fb265` | `feat: add sealed built-in capability registry` | 鍚庣画淇 |
| A5 淇 1 | `4f04cd126368f39d7c3ebad4d828897c85e750a3` | `fix: seal registry descriptor snapshots` | 鍚庣画淇 |
| A5 淇 2 | `604482e323e1479348844dbd2dd46ed7c9ac9c13` | `fix: resolve sealed registry adapters` | 鐙珛瀹℃煡閫氳繃 |
| A6 | `ffa1a05b9e65bd9cbcd0ebb8281797dab5e819ae` | `feat: add safe canonical math expression input` | 鍚庣画淇 |
| A6 淇 | `084c15a17684e32a03b898d0ff875faa8cb98c6d` | `fix: seal canonical expression snapshots` | 鐙珛瀹℃煡閫氳繃 |
| A7 | `e70fc0432730f48e9c1ecfcd2d3fd8820c44b247` | `feat: execute bisection root finding` | 鍚庣画淇 |
| A7 淇 | `d44e8023b8b10f7077559994d1d5c39c4e71340e` | `fix: preserve bisection termination order` | 鐙珛瀹℃煡閫氳繃 |
| A8 | `7719f2937d640ec90bc8b96cf8b1a6d007b3e459` | `feat: add independent residual validation` | 鐙珛瀹℃煡閫氳繃 |

鎴嚦璇ュ熀绾匡紝宸茬粡鍏峰锛?
- 閿佸畾鐨?Python/uv 寮€鍙戠幆澧冿紱
- 涓ユ牸宸ュ叿鍜岄敊璇?Schema锛?- 瀹夸富鏃犲叧鏍稿績杈圭晫锛?- SQLite schema 1 涓庡畨鍏ㄩ」鐩矾寰勶紱
- 灏佸瓨鐨勮兘鍔涙敞鍐岃〃锛?- 瀹夊叏琛ㄨ揪寮忚В鏋愬拰瑙勮寖杈撳叆锛?- 纭畾鎬т簩鍒嗘硶姹傛牴锛?- 涓庢眰瑙ｅ櫒鐙珛鐨勬畫宸獙璇佸櫒銆?
## 5. 褰撳墠鏈畬鎴愪簨椤?
### 5.1 姝ｅ湪杩涜

#### A9a锛欰9 鍓嶇疆濂戠害淇

褰撳墠宸ヤ綔鍖哄瓨鍦ㄥ皻鏈彁浜ょ殑 A9a 淇敼锛屼富瑕佸寘鎷細

- 灏嗚鑼冨寲鍚庣殑 `Experiment`銆乣Attempt` 鍜?`Validation` 浣滀负瀛樺偍绔彛杈撳叆锛?- 澧炲姞楠岃瘉鎵€闇€鐨勫彧璇?`ValidationSource`锛?- 绾︽潫閲嶆斁銆佺埗瀛愬叧绯汇€佺粨鏋滃揩鐓у綊灞炲拰 trace 涓€鑷存€э紱
- 鎻愪緵娣卞害涓嶅彲鍙樼殑 `ProjectStoreError`锛?- 鎻愪緵瀹夸富涓珛鐨勮緭鍏ユ嫆缁濄€佸畨鍏ㄨ繚瑙勩€侀鎵ц璧勬簮瓒呴檺銆佸彇娑堛€佹埅姝㈡椂闂村拰杩愯鏈熻祫婧?  瓒呴檺寮傚父锛?- 灏嗘眰鏍规ā鍧楃殑鍏蜂綋寮傚父鏄犲皠鍒颁笂杩版牳蹇冨绾︼紱
- 鍚屾 SQLite 閫傞厤鍣ㄧ殑绛惧悕鍗犱綅锛屼絾涓嶆彁鍓嶅疄鐜?SQL 琛屼负銆?
A9a 鏈€杩戜竴娆¤仛鐒﹂獙璇佷负 320 涓祴璇曢€氳繃锛屽叏閲忛獙璇佷负 532 涓祴璇曢€氳繃锛孯uff 鍜?MyPy
閫氳繃锛涗絾璇ヤ慨鏀逛粛鍦ㄦ彁浜ゅ墠鐙珛瀹¤涓紝鍥犳鏈枃浠朵笉鎶婂畠鏍囦负瀹屾垚銆傚璁″凡鍙戠幇
`x//2` 杩欑被鏈煡杩愮畻绗︿粛闇€绋冲畾鏄犲皠涓虹姝㈣娉曪紝淇骞堕噸鏂伴獙璇佸悗鎵嶈兘鎻愪氦銆?
### 5.2 M1a 鍓╀綑

1. 瀹屾垚 A9a銆佸垱寤烘彁浜ゅ苟閫氳繃鐙珛浠诲姟瀹℃煡銆?2. 瀹屾垚 A9b锛?   - `ModelingApplication` 鍏釜鐢ㄤ緥锛?   - SQLite 椤圭洰銆佸疄楠屻€丄ttempt銆丷esultSnapshot銆乂alidation 鍜屽箓绛変簨鍔★紱
   - 鍚岃繘绋嬮潪闃诲鍐欓棬涓庤繘绋嬬骇椤圭洰閿侊紱
   - 棰勬墽琛岄敊璇拰杩愯缁堟€佺殑绋冲畾鏄犲皠锛?   - 鐩存帴 Facade 榛勯噾閾捐矾涓庡鐜版祴璇曘€?3. 瀹屾垚 A10锛氫弗鏍?STDIO MCP 鍏伐鍏烽€傞厤鍜屽敮涓€缁勫悎鏍广€?4. 瀹屾垚 A11锛氱湡瀹?MCP 瀛愯繘绋嬮粍閲戦摼璺€佸畨鍏ㄦ祴璇曞拰 M1a evidence銆?5. 瀹屾垚 A12锛歞octor銆丄GENTS銆佷笂涓嬫枃绱㈠紩銆丆odex 閰嶇疆銆佺淮鎶ゆ枃妗ｅ拰楠屾敹鏄犲皠銆?6. 杩愯骞堕€氳繃 `modeling verify --milestone m1a`銆?
### 5.3 C1 鍓╀綑

C1.1鈥揅1.8 灏氭湭杩涘叆鐢熶骇瀹炵幇銆侻1a Hard Gate 閫氳繃鍓嶄笉寰楃紪鍐?C1 鐢熶骇浠ｇ爜銆傚悗缁渶瑕?瀹屾垚璧勪骇銆丮MIR銆亀orker銆佽€﹀悎鍨傝崱鑳藉姏銆佺嫭绔嬮獙璇併€丒xcel/鍥捐〃瀵煎嚭鍜岀湡瀹炲涓昏瘉鎹€?
### 5.4 M1b 鍓╀綑

B1鈥揃12 灏氭湭寮€濮嬨€傛寜褰撳墠鎵瑰噯璺嚎锛屽彧鏈?C1 Hard Gate 閫氳繃鍚庢墠鎭㈠瀹屾暣 M1b锛屽寘鎷?绋冲畾 1.0 Schema銆丷FC 8785 瀹屾暣绗﹀悎鎬с€佸唴瀹瑰鍧€鍒跺搧銆佹仮澶?閲嶆斁銆佹晠闅滄敞鍏ャ€?Windows/Ubuntu 鍙屽钩鍙伴獙璇佸拰姝ｅ紡鍙戝竷璇佹嵁銆?
### 5.5 鍚庣画閲岀▼纰?
Phase 0 杩樺畾涔変簡 M2鈥揗6 鐨勯暱鏈熸柟鍚戯細

- M2锛氳禌棰樸€侀檮浠跺拰鏁版嵁鍩虹锛?- M2.5锛氬彈鎺?worker銆佺‖瓒呮椂鍜岃祫婧愰檺鍒讹紱
- M3锛歁MIR銆佸姩鎬佸缓妯″伐浣滄祦鍜岄鎵?ODE/浼樺寲/缁熻鑳藉姏锛?- M4锛欵xcel銆佸浘琛ㄣ€佸疄楠屾瘮杈冨拰璁烘枃绱犳潗锛?- M5锛氶珮绾ц兘鍔涘拰鍙€?External Plugin锛?- M6锛欳laude Code銆乀RAE 鍜屽叾浠栦骇鍝佸舰鎬併€?
C1 浼氭彁鍓嶄互鏈夌晫棰勮鏂瑰紡楠岃瘉鍏朵腑閮ㄥ垎鑳藉姏锛屼絾涓嶄細鏇夸唬杩欎簺姝ｅ紡閲岀▼纰戙€?
## 6. 缁存姢璇存槑

鏈枃浠舵槸椤圭洰瀵艰埅鍜岀姸鎬佹憳瑕侊紝涓嶆浛浠ｆ潈濞佽鏍笺€傚彂鐢熷啿绐佹椂鎸変互涓嬮『搴忓鐞嗭細

1. 宸叉壒鍑嗚璁¤鏍间笌瀹炴柦璁″垝鍐冲畾鐩爣鍜岃竟鐣岋紱
2. 鐗堟湰鍖?Schema 鍜屽绾﹀喅瀹氬叕寮€鏁版嵁褰㈢姸锛?3. Git 鎻愪氦銆佹祴璇曡緭鍑哄拰 verifier 璇佹嵁鍐冲畾瀹為檯瀹屾垚鐘舵€侊紱
4. 鏈枃浠堕殢姣忎釜瀹屾垚骞堕€氳繃鐙珛瀹℃煡鐨勪换鍔℃洿鏂般€?
