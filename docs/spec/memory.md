# Project Memory

> å½“å‰æœ‰æ•ˆçš„æž¶æž„è®°å¿†ã€å·¥ä½œçº¦æŸä¸Žç¨³å®šçº¦å®šã€‚

---

## 1. Architecture Overview

å½“å‰ä»“åº“çš„çœŸå®žç»“æž„æ˜¯ï¼š

- ä¸€ä¸ªæ­£å¼å‰ç«¯å£³ï¼šExecutionView/frontend
- ä¸‰ä¸ªä¸šåŠ¡æ¨¡å—ï¼šMarketViewã€ExecutionViewã€CostView
- ä¸€ä¸ªé€»è¾‘æ•°æ®åŸŸå…¥å£ï¼šplatform_data

å…³é”®å…¥å£ï¼š

- å‰ç«¯å£³ï¼šfrontend/src/App.tsx
- åŽç«¯è£…é…å±‚ï¼šbackend/api/main.py
- CostView ç®¡çº¿ä¸Žåˆ†æžï¼šCostView/src/
- å…±äº«é€‚é…å±‚ï¼šplatform_data/adapters.py

---

## 2. Stable Design Rules

### å‰ç«¯

- ExecutionView/frontend æ˜¯å”¯ä¸€æ­£å¼ UI å…¥å£ã€‚
- CostView çš„æ­£å¼ UI ä½äºŽ frontend/src/modules/costview/ã€‚
- CostView/frontend/ æ˜¯é—ç•™åŽŸåž‹é¢ï¼Œä¸åº”å†æ‰¿æŽ¥é»˜è®¤äº§å“å¼€å‘ã€‚
- MarketView å½“å‰å·²æœ‰å£³å†…å…¥å£å’ŒçœŸå®žå¿«ç…§åŸºçº¿ï¼Œä½†åŽç»­æ‰©å±•å·²æš‚åœã€‚

### åŽç«¯

- backend/api/main.py çŽ°åœ¨ä¸»è¦è´Ÿè´£åº”ç”¨è£…é…ï¼Œä¸å†æ˜¯å”¯ä¸€ä¸šåŠ¡é€»è¾‘æ–‡ä»¶ã€‚
- Bloomberg é€»è¾‘æ ¸å¿ƒåœ¨ services/bloomberg_adapter.pyã€‚
- Python åŽç«¯ä»£ç ä¿®æ”¹åŽéœ€è¦é‡å¯åŽç«¯æ‰èƒ½ç”Ÿæ•ˆã€‚

### æ•°æ®åŸŸ

- ä¸€ä¸ªé€»è¾‘æ•°æ®åŸŸä¸ç­‰äºŽä¸€ä¸ªç‰©ç†æ•°æ®åº“ã€‚
- ExecutionView æ‹¥æœ‰ operational stateã€‚
- CostView æ‹¥æœ‰ analytical å’Œ pipeline æ•°æ®ã€‚
- è·¨åŸŸè®¿é—®ä¼˜å…ˆé€šè¿‡ platform_data/ é€‚é…å±‚ï¼Œè€Œä¸æ˜¯æ·±å±‚ç›´æŽ¥å¯¼å…¥ã€‚

---

## 3. Runtime Patterns

### æ•°æ®æŒä¹…åŒ–è¯­ä¹‰

- ENABLE_DB_PERSISTENCE=true æ—¶ï¼ŒåŽç«¯å¯åŠ¨ä¼šæ‰§è¡Œæ•°æ®åº“ bootstrapã€‚
- ENABLE_DB_PERSISTENCE=false æ—¶ï¼Œæ•°æ®åº“è¢«è§†ä¸ºå¯é€‰èƒ½åŠ›ã€‚
- åœ¨å¯é€‰æ¨¡å¼ä¸‹ï¼Œ/api/health åº”è¿”å›ž database.status=disabledï¼Œè€Œä¸æ˜¯ disconnectedã€‚

### Bloomberg ä¼šè¯æ¨¡å¼

- è®¢é˜…ã€è¯·æ±‚å“åº”ã€å¸‚åœºæ•°æ®/RefData å·²åˆ†ç¦»ï¼Œé¿å… nextEvent ç«žäº‰ã€‚
- RefData pending å¿…é¡»ä¸Žå¯¹åº” correlation id ç²¾ç¡®ç»‘å®šï¼Œä¸èƒ½å…¨å±€ç²—æš´æ¸…é›¶ã€‚

### FX æ±‡çŽ‡å¤„ç†

- direct ä¸Ž inverse åŒæ—¶å­˜åœ¨æ—¶ï¼Œinverse æ›´å¯é ã€‚
- å·²çŸ¥ 10x/100x/1000x ç¼©æ”¾æŠ¥ä»·åº”è§†ä¸ºæŠ¥ä»·çº¦å®šï¼Œè€Œä¸æ˜¯æŒç»­ WARNINGã€‚
- åªæœ‰ç¼©æ”¾å½’ä¸€åŒ–åŽä»æ˜¾è‘—åç¦»çš„ direct/inverse å·®å¼‚æ‰ä¿ç•™ WARNINGã€‚

---

## 4. Module Status

### Execution

- ä»æ˜¯å½“å‰æœ€æˆç†Ÿçš„ä¸šåŠ¡åŸŸã€‚
- è®¢å•ã€è·¯ç”±ã€è®¤è¯ã€è¿žæŽ¥ã€å®žæ—¶ç­‰èƒ½åŠ›å·²æ¨¡å—åŒ–åˆ° routers/services/repositoriesã€‚

### CostView

- æ˜¯æ´»è·ƒåˆ†æžåŸŸã€‚
- TCA æŸ¥è¯¢ã€å¸‚åœºæ•°æ®æ±‡æ€»ã€æ—¥æ›´ç®¡çº¿éƒ½ä»¥ CostView/src/ ä¸ºå‡†ã€‚

### MarketView

- ç¬¬ä¸€æ‰¹çœŸå®žæ•°æ®è¾¹ç•Œå·²è½åœ°ï¼šbdib_daily_summary å¿«ç…§ã€‚
- å½“å‰åªä¿ç•™åªè¯»åŸºçº¿ï¼Œä¸ç»§ç»­æ‰©åŠŸèƒ½ï¼Œç›´åˆ°æš‚åœè§£é™¤ã€‚

---

## 5. Documentation Rules

- docs æ ¹ç›®å½•åªä¿ç•™ä»ç„¶æœ‰æ•ˆçš„è¿è¡ŒæŒ‡å—ã€æž¶æž„è¯´æ˜Žã€æ•°æ®è¾¹ç•Œã€å½“å‰ handoff å’Œæ´»è·ƒè®¡åˆ’æ–‡æ¡£ã€‚
- å·²å®Œæˆé˜¶æ®µæ€»ç»“ã€ä¸€æ¬¡æ€§è¯Šæ–­æŠ¥å‘Šã€æ—§æž¶æž„è·¯å¾„è¯´æ˜Žï¼Œåº”ç§»å…¥ docs/archive/æ—¥æœŸç›®å½•ã€‚
- ç»“æž„æ€§å†³ç­–å†™å…¥ .github/knowledge/architecture-decisions.mdã€‚
- è¿è¡Œæ—¶é”™è¯¯æ¨¡å¼å†™å…¥ .github/knowledge/error-patterns.mdã€‚

---

## 6. Operational Reminders

- Bloomberg å­—æ®µå¿…é¡»è¿›å…¥è®¢é˜…åˆ—è¡¨æ‰ä¼šæ”¶åˆ°ã€‚
- Bloomberg å­—æ®µç±»åž‹å¿…é¡»ä¸Žè§£æžå™¨ç±»åž‹ä¸€è‡´ã€‚
- é»˜è®¤æ—¥å¿—çº§åˆ«ä¸º WARNINGï¼Œå› æ­¤æ–°å¢žè¯Šæ–­æ—¥å¿—è¦è°¨æ…ŽæŽ§åˆ¶ç­‰çº§ã€‚
- MarketViewã€CostViewã€ExecutionView çš„å…±äº«æ•°æ®æŽ¥å…¥ä¼˜å…ˆä»Ž platform_data è¿›å…¥ã€‚

---

## 7. DatabaseView API Contract

è§ `docs/api/database.md`ã€‚DatabaseView æ˜¯ ExecutionView/frontend çš„ç¬¬ 4 ä¸ªé¡¶å±‚æ¨¡å—ï¼Œè´Ÿè´£å¯è§†åŒ– CostView
SQLite æ•°æ®åº“æ—çš„äº¤æ˜“æ—¥æœŸè¦†ç›–ã€è¡Œæ•°ä¸Žå¥åº·çŠ¶æ€ã€‚

