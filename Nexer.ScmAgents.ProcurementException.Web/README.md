# Nexer SCM AI Agents — Web UI

React UI for the Procurement Exception Agent platform.
Submits SCM events to the dev API and displays Top 3 recommendations
for human approval.

## Run

Terminal 1 — API (agent pipeline):

```powershell
cd C:\development\SCMAgentsPack\Nexer.ScmAgents.ProcurementException
az login   # once per session
.venv\Scripts\python.exe scripts\dev_api_server.py
```

Wait for: `Dev API listening on http://127.0.0.1:7071/`

Terminal 2 — UI:

```powershell
cd C:\development\SCMAgentsPack\Nexer.ScmAgents.ProcurementException.Web
npm install   # first time only
npm run dev
```

Open http://localhost:5173
