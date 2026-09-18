import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { ProtectedLayout } from "./layout/AppLayout";
import { ImportWizardPage } from "./imports/ImportWizardPage";
import { ImportProgressPage } from "./imports/ImportProgressPage";
import { GeocodingTrayPage } from "./geocoding/GeocodingTrayPage";
import { OperationalMapPage } from "./map/OperationalMapPage";
import { ZoneEditorPage } from "./zoning/ZoneEditorPage";
import { PlanCalendarPage } from "./planning/PlanCalendarPage";
import { OptimizerPage } from "./routing/OptimizerPage";
import { HistoryPage } from "./history/HistoryPage";
import { FieldPage } from "./field/FieldPage";
import { SharingPage } from "./sharing/SharingPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedLayout />}>
            <Route path="/mapa" element={<OperationalMapPage />} />
            <Route path="/zonas" element={<ZoneEditorPage />} />
            <Route path="/planificacion" element={<PlanCalendarPage />} />
            <Route path="/optimizacion" element={<OptimizerPage />} />
            <Route path="/historico" element={<HistoryPage />} />
            <Route path="/campo" element={<FieldPage />} />
            <Route path="/compartir" element={<SharingPage />} />
            <Route path="/importar" element={<ImportWizardPage />} />
            <Route path="/importar/:batchId" element={<ImportProgressPage />} />
            <Route path="/geocodificacion" element={<GeocodingTrayPage />} />
          </Route>
          <Route path="/" element={<Navigate to="/mapa" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
