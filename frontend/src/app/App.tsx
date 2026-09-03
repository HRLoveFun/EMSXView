// Platform Shell — entry point
// Side-effect imports: module registries register themselves before AppShell queries them.
import '../modules/execution/module.registry';
import '../modules/marketview/module.registry';
import '../modules/costview/module.registry';
// 010-extract-pipeline: databaseview 模块已迁独立项目 EMSXDataPipeline Runner，
// EMSXView 前端不再承载数据库维护 UI。

import { AppShell } from './AppShell';
import '../App.css';

function App() {
  return <AppShell />;
}

export default App;
