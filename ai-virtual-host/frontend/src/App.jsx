import EventForm from "./pages/EventForm";
import LiveStatus from "./pages/LiveStatus";
import LogsPage from "./pages/LogsPage";

function App() {
  const path = window.location.pathname;

  if (path === "/live") {
    return <LiveStatus />;
  }

  if (path === "/logs") {
    return <LogsPage />;
  }

  return <EventForm />;
}

export default App;
