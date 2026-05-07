# EMSX å¼€å‘æŒ‡å—

> Last updated: 2026-05-06 | Version: 2.1

## 1. å¿«é€Ÿå¯åŠ¨

æŽ¨èå…¥å£ï¼š

- ä»“åº“æ ¹ç›®å½•è¿è¡Œ start-services.bat
- æˆ–ä½¿ç”¨ scripts ä¸‹çš„ start-all.bat / restart-all.bat / check-status.bat

æŒ‰æ¨¡å—å•ç‹¬å¯åŠ¨ï¼š

```powershell
# åŽç«¯
Set-Location ExecutionView/backend/api
python start_server.py

# å‰ç«¯
Set-Location ExecutionView/frontend
npm run dev
```

å¸¸ç”¨æ£€æŸ¥ï¼š

- å¥åº·æ£€æŸ¥ï¼šhttp://localhost:3000/api/health
- å¸‚åœºå¿«ç…§åŸºçº¿ï¼šhttp://localhost:3000/api/marketview/snapshot?limit=3
- å‰ç«¯å¼€å‘æœåŠ¡ï¼šhttp://localhost:5173

## 2. å½“å‰å·¥ç¨‹äº‹å®ž

å½“å‰ä»“åº“ä¸æ˜¯â€œä¸‰å¥—ç‹¬ç«‹åº”ç”¨â€ï¼Œè€Œæ˜¯ï¼š

- ä¸€ä¸ªæ­£å¼å‰ç«¯å£³ï¼šExecutionView/frontend/src/App.tsx
- ä¸‰ä¸ªä¸šåŠ¡æ¨¡å—ï¼šMarketViewã€ExecutionViewã€CostView
- ä¸€ä¸ªé€»è¾‘æ•°æ®åŸŸå…¥å£ï¼šplatform_data/

å½“å‰æƒå¨å®žçŽ°é¢ï¼š

- å‰ç«¯å£³ï¼šExecutionView/frontend/
- åŽç«¯è£…é…å±‚ï¼šExecutionView/backend/api/
- CostView åˆ†æžä¸Žç®¡çº¿ï¼šCostView/src/
- å…±äº«æ•°æ®é€‚é…å±‚ï¼šplatform_data/

é‡è¦è¿è¡Œè¯­ä¹‰ï¼š

- Python åŽç«¯æ”¹åŠ¨åŽå¿…é¡»é‡å¯åŽç«¯ã€‚
- ENABLE_DB_PERSISTENCE=false æ—¶ï¼Œæ•°æ®åº“è¢«è§†ä¸ºå¯é€‰èƒ½åŠ›ï¼›/api/health ä¼šè¿”å›ž database=disabledã€‚
- Bloomberg ç›¸å…³å­—æ®µå¦‚æžœä¸åœ¨è®¢é˜…åˆ—è¡¨ä¸­ï¼Œå°±ä¸ä¼šæ”¶åˆ°ã€‚
- Bloomberg å­—æ®µç±»åž‹å¿…é¡»ä¸Žè§£æžå™¨ç±»åž‹ä¸€è‡´ã€‚

## 3. éªŒè¯æ¸…å•

å‰ç«¯æ”¹åŠ¨ï¼š

- åœ¨ ExecutionView/frontend è¿è¡Œ npm run build

åŽç«¯æ”¹åŠ¨ï¼š

- ä¼˜å…ˆè¿è¡Œå—å½±å“åˆ‡é¢çš„ pytestï¼Œè€Œä¸æ˜¯åªåšå…¨é‡è¯­æ³•æ£€æŸ¥
- å¦‚ä¿®æ”¹äº†è¿è¡Œæ—¶è¡Œä¸ºï¼Œé‡å¯åŽç«¯å¹¶åšä¸€æ¬¡æŽ¥å£ smoke test

æ–‡æ¡£æ”¹åŠ¨ï¼š

- æ›´æ–° docs/index.md ä¸­çš„æ–‡æ¡£åˆ†å±‚æˆ–å…¥å£è¯´æ˜Ž
- å¦‚æ”¹å˜æž¶æž„è¡¨è¿°ï¼ŒåŒæ—¶æ£€æŸ¥ docs/spec/project-structure.mdã€docs/spec/data-domain.mdã€docs/spec/memory.md
- å¦‚æ”¹å˜å½“å‰è¿è¡ŒçŠ¶æ€æˆ–é˜»å¡žé¢ï¼ŒåŒæ—¶æ£€æŸ¥ docs/handoff.md

## 4. å¸¸è§ä»»åŠ¡å…¥å£

### æ·»åŠ æˆ–è°ƒæ•´åŽç«¯èƒ½åŠ›

ä¼˜å…ˆæ£€æŸ¥è¿™äº›ä½ç½®ï¼š

- è·¯ç”±ï¼šExecutionView/backend/api/routers/
- æœåŠ¡ï¼šExecutionView/backend/api/services/
- æ•°æ®å¥‘çº¦ï¼šExecutionView/backend/api/schemas.py
- å…±äº«é€‚é…ï¼šplatform_data/

### è°ƒæ•´è·¨åŸŸæ•°æ®è®¿é—®

ä¼˜å…ˆèµ° platform_data/ï¼Œä¸è¦é»˜è®¤æ–°å¢žæ·±å±‚ç›´æŽ¥å¯¼å…¥ã€‚

å…¸åž‹é¡ºåºï¼š

1. åœ¨ platform_data/adapters.py å¢žåŠ æˆ–æ‰©å±•é€‚é…å™¨
2. ä¿®æ”¹è°ƒç”¨æ–¹è·¯ç”±æˆ–æœåŠ¡
3. è¡¥å¯¹åº”æµ‹è¯•
4. åŒæ­¥å‰ç«¯ç±»åž‹æˆ–å±•ç¤º

### è°ƒè¯• Bloomberg è¿è¡Œæ—¶é—®é¢˜

ä¼˜å…ˆæŸ¥çœ‹ï¼š

- logs/emsx_api.log åŠå…¶è½®è½¬æ–‡ä»¶
- .github/knowledge/error-patterns.md
- docs/handoff.md ä¸­çš„å½“å‰è¿è¡ŒçŠ¶æ€

## 5. å½“å‰æ–‡æ¡£åœ°å›¾

ä¼˜å…ˆé˜…è¯»é¡ºåºï¼š

1. docs/index.mdï¼šæ–‡æ¡£å…¥å£ä¸Žåˆ†ç±»
2. docs/spec/project-structure.mdï¼šå½“å‰ä»“åº“ç»“æž„ä¸Žæƒå¨å®žçŽ°é¢
3. docs/spec/data-domain.mdï¼šé€»è¾‘æ•°æ®åŸŸè¾¹ç•Œ
4. docs/spec/memory.mdï¼šç¨³å®šæž¶æž„è®°å¿†ä¸Žå·¥ä½œçº¦æŸ
5. docs/handoff.mdï¼šå½“å‰é˜»å¡žã€è¿è¡ŒçŠ¶æ€ã€ä¸‹ä¸€æ­¥

çŸ¥è¯†åº“ä½ç½®ï¼š

- æž¶æž„å†³ç­–ï¼š.github/knowledge/architecture-decisions.md
- é”™è¯¯æ¨¡å¼ï¼š.github/knowledge/error-patterns.md
- ç”¨æˆ·éœ€æ±‚ï¼š.github/knowledge/user-needs.md
- è¿­ä»£æ—¥å¿—ï¼š.github/knowledge/iteration-log.md

## 6. å·¥ä½œçº¦æŸ

- ä¸è¦æŠŠ CostView/frontend å½“æˆæ­£å¼å‰ç«¯å…¥å£ã€‚
- ä¸è¦å†ç”¨ app/ æˆ– emsx-backend/ ä½œä¸ºå½“å‰ç»“æž„æè¿°ã€‚
- æ–°çš„ä¸“é¢˜æ€»ç»“ç±»æ–‡æ¡£å¦‚æžœåªå¯¹åº”ä¸€æ¬¡æ€§é—®é¢˜æˆ–å·²å®Œæˆé˜¶æ®µï¼Œåº”æ”¾å…¥ docs/archive/ è€Œä¸æ˜¯é•¿æœŸç•™åœ¨ docs æ ¹ç›®å½•ã€‚
- é•¿æœŸæœ‰æ•ˆçš„æ–‡æ¡£æ‰ç•™åœ¨ docs æ ¹ç›®å½•ï¼šè¿è¡ŒæŒ‡å—ã€æž¶æž„è¯´æ˜Žã€æ•°æ®è¾¹ç•Œã€å½“å‰ handoffã€æŒç»­ç»´æŠ¤çš„è®¡åˆ’æ–‡æ¡£ã€‚


