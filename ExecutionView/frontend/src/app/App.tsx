// Platform Shell — entry point
// Side-effect imports: module registries register themselves before AppShell queries them.
import '../modules/execution/module.registry';
import '../modules/marketview/module.registry';
import '../modules/costview/module.registry';
import '../modules/databaseview/module.registry';

import { AppShell } from './AppShell';
import '../App.css';

function App() {
  return <AppShell />;
}

export default App;
