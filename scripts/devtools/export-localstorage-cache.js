/**
 * Export LocalStorage Cache Script
 * 
 * This script simulates the browser's LocalStorage export functionality.
 * In a real browser environment, this runs when you click "Export Config" in the UI.
 * 
 * Usage:
 * 1. Open browser DevTools (F12)
 * 2. Go to Console tab
 * 3. Paste and run this script
 * 4. Or use the "Export Config" button in the Strategy Data Manager UI
 */

// Simulate the export function that runs in browser
function exportLocalStorageCache() {
  const brokers = {};
  const params = {};

  console.log('[Export] Starting LocalStorage scan for cached API data...');
  console.log('[Export] This exports real Bloomberg API data cached in your browser');

  if (typeof localStorage === 'undefined') {
    console.error('[Export] LocalStorage not available. Run this in browser console.');
    return null;
  }

  const totalKeys = localStorage.length;
  console.log(`[Export] Scanning ${totalKeys} LocalStorage entries...`);

  let strategiesFound = 0;
  let paramsFound = 0;

  // Scan all LocalStorage keys
  for (let i = 0; i < totalKeys; i++) {
    const key = localStorage.key(i);
    if (!key) continue;

    // Look for broker strategies cache: emsx_cache_broker_strategies_{broker}
    const strategiesMatch = key.match(/^emsx_cache_broker_strategies_(.+)$/);
    if (strategiesMatch) {
      try {
        const broker = strategiesMatch[1];
        const rawData = localStorage.getItem(key);
        const data = JSON.parse(rawData || '{}');
        
        if (data.data && data.data.strategies) {
          console.log(`[Export] ✓ Found strategies for ${broker}:`, data.data.strategies);
          brokers[broker] = {
            assetClasses: [data.data.assetClass || 'EQTY'],
            strategies: data.data.strategies,
          };
          strategiesFound++;
        }
      } catch (e) {
        console.warn(`[Export] ✗ Failed to parse strategies cache for key ${key}:`, e);
      }
    }

    // Look for strategy info cache: emsx_cache_strategy_info_{broker}_{strategy}
    const infoMatch = key.match(/^emsx_cache_strategy_info_(.+)_(.+)$/);
    if (infoMatch) {
      try {
        const broker = infoMatch[1];
        const strategy = infoMatch[2];
        const rawData = localStorage.getItem(key);
        const data = JSON.parse(rawData || '{}');
        
        if (data.data && data.data.fields) {
          console.log(`[Export] ✓ Found params for ${broker}/${strategy}:`, data.data.fields.length, 'fields');
          if (!params[broker]) {
            params[broker] = {};
          }
          params[broker][strategy] = {
            fields: data.data.fields,
          };
          paramsFound++;
        }
      } catch (e) {
        console.warn(`[Export] ✗ Failed to parse strategy info cache for key ${key}:`, e);
      }
    }
  }

  console.log(`\n[Export] Scan complete!`);
  console.log(`[Export] Found ${strategiesFound} broker(s) with strategies`);
  console.log(`[Export] Found ${paramsFound} strategy parameter set(s)`);

  if (strategiesFound === 0 && paramsFound === 0) {
    console.log('\n[Export] No cached data found. You need to:');
    console.log('  1. Connect to Bloomberg API');
    console.log('  2. Use strategy features (e.g., modify route strategy)');
    console.log('  3. Data will be cached automatically');
    console.log('  4. Then run this export again');
    return null;
  }

  // Build export data
  const exportData = {
    version: '1.0',
    exportedAt: new Date().toISOString(),
    description: 'Exported from LocalStorage cache - REAL Bloomberg API data',
    source: 'Bloomberg API via LocalStorage cache',
    brokers,
    strategies: params,
  };

  // Output formatted JSON
  console.log('\n[Export] === EXPORT DATA (Copy this to your JSON files) ===\n');
  console.log(JSON.stringify(exportData, null, 2));
  
  console.log('\n[Export] === INSTRUCTIONS ===');
  console.log('1. Copy the "brokers" section to: public/strategy-data/default-strategies.json');
  console.log('2. Copy the "strategies" section to: public/strategy-data/default-strategy-params.json');
  console.log('3. In the UI, click "Strategy Data" → "Reload Files"');
  console.log('4. You can now use these cached data when offline');

  return exportData;
}

// Auto-run if in browser
if (typeof window !== 'undefined') {
  exportLocalStorageCache();
} else {
  console.log('This script should be run in browser console.');
  console.log('Open DevTools (F12) → Console, then paste and run this script.');
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { exportLocalStorageCache };
}
