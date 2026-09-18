import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import { listPlanRoutes, listPlans } from "../api/planning";
import {
  createExternalShare,
  createInternalShare,
  exchangePublicShare,
  listShares,
  revokeShare,
} from "../api/sharing";
import { listZones } from "../api/zoning";
import type {
  DailyRouteSummary,
  PlanListItem,
  PublicShareView,
  ShareGrant,
  SharePermission,
  ZoneSummary,
} from "../api/types";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.body.detail : fallback;
}

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

function defaultExpiry(): string {
  const stamp = new Date();
  stamp.setUTCDate(stamp.getUTCDate() + 7);
  return stamp.toISOString().slice(0, 10);
}

function toIsoEndOfDay(dateValue: string): string {
  return `${dateValue}T23:59:00.000Z`;
}

export function SharingPage() {
  const { organizationId } = useAuth();
  const [plans, setPlans] = useState<PlanListItem[]>([]);
  const [zones, setZones] = useState<ZoneSummary[]>([]);
  const [routes, setRoutes] = useState<DailyRouteSummary[]>([]);
  const [planId, setPlanId] = useState("");
  const [routeId, setRouteId] = useState("");
  const [grants, setGrants] = useState<ShareGrant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [subjectUserId, setSubjectUserId] = useState("");
  const [permission, setPermission] = useState<SharePermission>("view");
  const [internalExpiry, setInternalExpiry] = useState("");
  const [externalExpiry, setExternalExpiry] = useState(defaultExpiry);
  const [riskConfirmed, setRiskConfirmed] = useState(false);
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [preview, setPreview] = useState<PublicShareView | null>(null);

  const zoneName = useCallback(
    (zoneId: string) => zones.find((zone) => zone.id === zoneId)?.name ?? zoneId.slice(0, 8),
    [zones],
  );

  const loadGrants = useCallback(
    async (id: string) => {
      if (!organizationId || !id) {
        setGrants([]);
        return;
      }
      const page = await listShares(id, organizationId);
      setGrants(page.grants);
    },
    [organizationId],
  );

  useEffect(() => {
    if (!organizationId) return;
    Promise.all([listPlans(organizationId), listZones(organizationId)])
      .then(([planResponse, zoneResponse]) => {
        setPlans(planResponse.plans);
        setZones(zoneResponse.zones);
        const published = planResponse.plans.find((item) => item.status === "published");
        setPlanId(published?.id ?? planResponse.plans[0]?.id ?? "");
      })
      .catch((err: unknown) => {
        setError(errorMessage(err, "No se pudieron cargar los planes"));
      });
  }, [organizationId]);

  useEffect(() => {
    if (!organizationId || !planId) {
      setRoutes([]);
      setRouteId("");
      return;
    }
    listPlanRoutes(planId, organizationId)
      .then((response) => {
        setRoutes(response.routes);
        setRouteId(response.routes[0]?.id ?? "");
      })
      .catch((err: unknown) => {
        setError(errorMessage(err, "No se pudieron cargar las rutas"));
      });
  }, [organizationId, planId]);

  useEffect(() => {
    if (!routeId) {
      setGrants([]);
      setPreview(null);
      setIssuedToken(null);
      return;
    }
    loadGrants(routeId).catch((err: unknown) => {
      setError(errorMessage(err, "No se pudieron cargar las comparticiones"));
    });
  }, [routeId, loadGrants]);

  const handleInternal = async (event: FormEvent) => {
    event.preventDefault();
    if (!organizationId || !routeId || !subjectUserId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createInternalShare({
        routeId,
        organizationId,
        subjectUserId: subjectUserId.trim(),
        permission,
        expiresAt: internalExpiry ? toIsoEndOfDay(internalExpiry) : undefined,
        idempotencyKey: newIdempotencyKey(),
      });
      setSubjectUserId("");
      await loadGrants(routeId);
    } catch (err) {
      setError(errorMessage(err, "No se pudo crear la compartición interna"));
    } finally {
      setBusy(false);
    }
  };

  const handleExternal = async (event: FormEvent) => {
    event.preventDefault();
    if (!organizationId || !routeId || !riskConfirmed) return;
    setBusy(true);
    setError(null);
    try {
      const grant = await createExternalShare({
        routeId,
        organizationId,
        expiresAt: toIsoEndOfDay(externalExpiry),
        idempotencyKey: newIdempotencyKey(),
      });
      setIssuedToken(grant.token ?? null);
      if (grant.token) {
        const view = await exchangePublicShare(grant.token);
        setPreview(view);
      }
      await loadGrants(routeId);
    } catch (err) {
      setError(errorMessage(err, "No se pudo crear el enlace externo"));
    } finally {
      setBusy(false);
    }
  };

  const handleRevoke = async (shareId: string) => {
    if (!organizationId) return;
    setBusy(true);
    setError(null);
    try {
      await revokeShare(shareId, organizationId);
      setIssuedToken(null);
      setPreview(null);
      await loadGrants(routeId);
    } catch (err) {
      setError(errorMessage(err, "No se pudo revocar la compartición"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page sharing">
      <h1>Compartir rutas</h1>
      <p>
        Comparte con usuarios de la organización o con un enlace externo. El enlace no
        incluye nombre, referencia, dirección ni estado de visita.
      </p>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      <form className="form sharing__filters">
        <label htmlFor="share-plan">Plan</label>
        <select
          id="share-plan"
          data-testid="share-plan"
          value={planId}
          onChange={(event) => setPlanId(event.target.value)}
        >
          {plans.length === 0 ? <option value="">Sin planes</option> : null}
          {plans.map((item) => (
            <option key={item.id} value={item.id}>
              {item.period} ({item.status})
            </option>
          ))}
        </select>
        <label htmlFor="share-route">Ruta</label>
        <select
          id="share-route"
          data-testid="share-route"
          value={routeId}
          onChange={(event) => setRouteId(event.target.value)}
        >
          {routes.length === 0 ? <option value="">Sin rutas</option> : null}
          {routes.map((item) => (
            <option key={item.id} value={item.id}>
              {item.service_date} · {zoneName(item.zone_id)}
            </option>
          ))}
        </select>
      </form>

      <div className="sharing-layout">
        <form className="form card" onSubmit={handleInternal}>
          <h2>Compartición interna</h2>
          <label htmlFor="share-user">Identificador de usuario</label>
          <input
            id="share-user"
            data-testid="share-user"
            value={subjectUserId}
            onChange={(event) => setSubjectUserId(event.target.value)}
            required
          />
          <label htmlFor="share-permission">Permiso</label>
          <select
            id="share-permission"
            data-testid="share-permission"
            value={permission}
            onChange={(event) => setPermission(event.target.value as SharePermission)}
          >
            <option value="view">Solo lectura</option>
            <option value="edit">Edición (si el rol lo permite)</option>
          </select>
          <label htmlFor="share-internal-expiry">Caducidad (opcional)</label>
          <input
            id="share-internal-expiry"
            data-testid="share-internal-expiry"
            type="date"
            value={internalExpiry}
            onChange={(event) => setInternalExpiry(event.target.value)}
          />
          <button type="submit" data-testid="share-internal-submit" disabled={busy || !routeId}>
            Compartir internamente
          </button>
        </form>

        <form className="form card" onSubmit={handleExternal}>
          <h2>Enlace externo</h2>
          <p>
            El destinatario verá solo el orden de paradas, sin datos de pacientes. Hace falta
            una política jurídica para compartir direcciones.
          </p>
          <label htmlFor="share-external-expiry">Caducidad</label>
          <input
            id="share-external-expiry"
            data-testid="share-external-expiry"
            type="date"
            value={externalExpiry}
            onChange={(event) => setExternalExpiry(event.target.value)}
            required
          />
          <label className="sharing__risk">
            <input
              type="checkbox"
              data-testid="share-risk"
              checked={riskConfirmed}
              onChange={(event) => setRiskConfirmed(event.target.checked)}
            />
            Confirmo el riesgo: el enlace no debe usarse para enviar datos de pacientes.
          </label>
          <button
            type="submit"
            data-testid="share-external-submit"
            disabled={busy || !routeId || !riskConfirmed}
          >
            Crear enlace externo
          </button>
        </form>
      </div>

      {issuedToken ? (
        <div className="banner" data-testid="share-token-once">
          <p>Token (solo se muestra una vez):</p>
          <code data-testid="share-token">{issuedToken}</code>
        </div>
      ) : null}

      {preview ? (
        <div className="card" data-testid="share-preview">
          <h2>Vista previa minimizada</h2>
          <p data-testid="share-preview-date">Fecha de visita: {preview.service_date}</p>
          <p data-testid="share-preview-count">{preview.stop_count} paradas (solo orden)</p>
          <ol data-testid="share-preview-stops">
            {preview.stops.map((stop) => (
              <li key={stop.sequence}>Parada {stop.sequence}</li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="card">
        <h2>Comparticiones activas</h2>
        {grants.length === 0 ? (
          <p data-testid="share-empty">No hay comparticiones activas en esta ruta.</p>
        ) : (
          <table className="data-table" data-testid="share-grants">
            <thead>
              <tr>
                <th>Tipo</th>
                <th>Permiso</th>
                <th>Destino</th>
                <th>Caduca</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {grants.map((grant) => (
                <tr key={grant.id}>
                  <td>{grant.kind === "external" ? "Externo" : "Interno"}</td>
                  <td>{grant.permission}</td>
                  <td>{grant.subject_user_id ?? "enlace"}</td>
                  <td>{grant.expires_at ? grant.expires_at.slice(0, 10) : "Sin caducidad"}</td>
                  <td>
                    <button
                      type="button"
                      className="button-secondary"
                      data-testid={`share-revoke-${grant.id}`}
                      disabled={busy}
                      onClick={() => {
                        void handleRevoke(grant.id);
                      }}
                    >
                      Revocar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
