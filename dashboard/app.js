// Observatoire de la sécheresse : dashboard (SPEC §8.2).
// Lit l'API de la même origine ; carte MapLibre (fond Plan IGN), graphiques ECharts.
// Les textes venant des données sont insérés avec textContent (jamais innerHTML), ou
// échappés dans les info-bulles des graphiques.

/* global echarts */

// MapLibre 6 n'est publié qu'en module ES (plus de variable globale)
import * as maplibregl from "https://cdn.jsdelivr.net/npm/maplibre-gl@6.13.0/dist/maplibre-gl.mjs";

const IGN =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
  "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM" +
  "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/png";

const NOMS_INDICES = {
  composite: "Indice composite", spi_3: "SPI 3 mois (pluie)", ips: "IPS (nappes)",
  debit: "Débits",
};
const COMPOSANTES_ABSENTES = { spi_3: "pluie (SPI 3 mois)", ips: "nappes (IPS)", debit: "débits" };
// Trois premières couleurs de la palette catégorielle de référence (validées deux à deux)
const COULEURS_COMPOSANTES = { spi_3: "#2a78d6", ips: "#eb6834", debit: "#1baf7a" };
const SOURCES = {
  piezo: "Piézomètre", hydro: "Station hydrométrique", onde: "Station ONDE", retenue: "Retenue",
};
// Modalités ONDE, de la plus humide à la plus sèche (Map : l'ordre est garanti)
const MODALITES = new Map([
  ["1", ["Écoulement visible", "#ffffd4"]], ["1a", ["Écoulement visible acceptable", "#fed98e"]],
  ["1f", ["Écoulement visible faible", "#fe9929"]], ["2", ["Écoulement non visible", "#d95f0e"]],
  ["3", ["Assec", "#993404"]],
]);
const PLANCHER_DEBIT = 1; // l/s : échelle logarithmique, un débit nul s'affiche à ce plancher
const REMPLISSAGE = [[0, "#deebf7"], [20, "#9ecae1"], [40, "#4292c6"], [60, "#2171b5"], [80, "#084594"]];
const TRAIT = "path://M0,4 L14,4 L14,6 L0,6 Z"; // clé de légende des courbes
const PLAGES = { "1 an": 1, "2 ans": 2, "10 ans": 10, Tout: 60 };
const GRIS = { axe: "#c9c8c2", grille: "#ecebe6", texte: "#52514e", enveloppe: "rgba(82,81,78,0.14)", mediane: "#8f8e88" };

const etat = {
  territoire: "", version: "", classes: [], seuils: [], semaines: [], semaine: null,
  zones: null, stations: null, synthese: null, selection: null, plage: "2 ans",
};
let carte;
const bulle = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });

// --- Outils -------------------------------------------------------------------------------

const nombre = (v, chiffres = 2) =>
  v === null || v === undefined ? "—" : new Intl.NumberFormat("fr-FR", { maximumFractionDigits: chiffres }).format(v);
const pourcent = (v, chiffres = 1) => `${nombre(v, chiffres)}\u00a0%`;
const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const etiquetteDate = (v) => {
  const d = new Date(v);
  if (d.getMonth() === 0 && d.getDate() === 1) return `{annee|${d.getFullYear()}}`;
  return d.getDate() === 1 ? MOIS[d.getMonth()] : `${d.getDate()} ${MOIS[d.getMonth()]}`;
};
const dateFr = (d) => new Date(d).toLocaleDateString("fr-FR", { timeZone: "UTC" });
const echapper = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function el(balise, attributs = {}, ...enfants) {
  const e = document.createElement(balise);
  for (const [cle, valeur] of Object.entries(attributs)) {
    if (cle === "class") e.className = valeur;
    else if (cle === "style") Object.assign(e.style, valeur);
    else if (cle.startsWith("on")) e.addEventListener(cle.slice(2), valeur);
    else if (valeur !== null && valeur !== undefined && valeur !== false) e.setAttribute(cle, valeur === true ? "" : valeur);
  }
  for (const enfant of enfants.flat()) {
    if (enfant !== null && enfant !== undefined && enfant !== false) e.append(enfant instanceof Node ? enfant : String(enfant));
  }
  return e;
}

async function api(chemin) {
  const reponse = await fetch(chemin);
  if (!reponse.ok) throw new Error(`${chemin} : erreur ${reponse.status}`);
  return reponse.json();
}

// --- Source des données : l'API (local) ou les fichiers exportés (GitHub Pages, make site) ---

const STATIQUE = Boolean(window.OBSERVATOIRE?.statique);
const memoire = new Map();
const fichier = (chemin) => {
  if (!memoire.has(chemin)) memoire.set(chemin, api(chemin));
  return memoire.get(chemin);
};
const dansPlage = (valeur, debut, fin) => valeur >= debut && valeur <= fin;

const source = STATIQUE ? {
  generalites: () => Promise.all(["accueil", "classes", "semaines"].map((n) => fichier(`donnees/${n}.json`))),
  async semaine(semaine) {
    const [zones, stations, annee] = await Promise.all([
      fichier("donnees/zones.geojson"), fichier("donnees/stations.geojson"), fichier(`donnees/semaines/${semaine.slice(0, 4)}.json`),
    ]);
    const donnees = annee[semaine];
    if (!donnees) throw new Error(`semaine ${semaine} absente de l'export`);
    // Contours (une seule fois) + indicateurs de la semaine
    const fusion = (geo, indicateurs, cle) => ({
      type: "FeatureCollection",
      features: geo.features.map((f) => ({ ...f, properties: { ...f.properties, semaine, ...(indicateurs[f.properties[cle]] ?? {}) } })),
    });
    return { zones: fusion(zones, donnees.zones, "zone_id"), stations: fusion(stations, donnees.stations, "station_id"), synthese: donnees.synthese };
  },
  async serieZone(zoneId, indice, debut, fin) {
    const series = await fichier(`donnees/series/zones/${zoneId}.json`);
    return { points: series[indice].filter((p) => dansPlage(p.semaine, debut, fin)) };
  },
  async serieStation(stationId, debut, fin) {
    const station = (await fichier("donnees/stations.geojson")).features.find((f) => f.properties.station_id === stationId);
    if (!station) throw new Error(`station inconnue : ${stationId}`);
    const serie = await fichier(`donnees/series/stations/${station.properties.fichier}.json`);
    const [semaineDebut, semaineFin] = [semaineDe(new Date(`${debut}T00:00:00Z`)), semaineDe(new Date(`${fin}T00:00:00Z`))];
    return {
      ...serie,
      chronique: { ...serie.chronique, points: serie.chronique.points.filter((p) => dansPlage(p.date, debut, fin)) },
      indices: serie.indices.filter((i) => dansPlage(i.semaine, semaineDebut, semaineFin)),
    };
  },
} : {
  generalites: () => Promise.all([api("/"), api("/classes"), api("/semaines")]),
  async semaine(semaine) {
    const [zones, stations, synthese] = await Promise.all([
      api(`/zones?semaine=${semaine}`), api(`/stations?semaine=${semaine}`), api(`/semaines/${semaine}/synthese`),
    ]);
    return { zones, stations, synthese };
  },
  serieZone: (zoneId, indice, debut, fin) => api(`/zones/${zoneId}/series?indice=${indice}&debut=${debut}&fin=${fin}`),
  serieStation: (stationId, debut, fin) => api(`/stations/${stationId}/series?debut=${debut}&fin=${fin}`),
};

function alerte(message) {
  const bloc = document.getElementById("alerte");
  bloc.hidden = !message;
  bloc.textContent = message || "";
}

// Semaines ISO « AAAA-Www » (dates en UTC)
function lundiDe(semaine) {
  const [annee, numero] = semaine.split("-W").map(Number);
  const quatreJanvier = new Date(Date.UTC(annee, 0, 4));
  const jour = quatreJanvier.getUTCDay() || 7;
  return new Date(Date.UTC(annee, 0, 4 - jour + 1 + (numero - 1) * 7));
}
const dimancheDe = (semaine) => new Date(lundiDe(semaine).getTime() + 6 * 86400000);
function semaineDe(date) {
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const numero = Math.ceil(((d - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(numero).padStart(2, "0")}`;
}
const iso = (d) => d.toISOString().slice(0, 10);
const numeroSemaine = (date) => Math.min(Number(semaineDe(date).slice(6)), 52); // 53 -> normale de 52

function debutPlage() {
  const fin = dimancheDe(etat.semaine);
  return new Date(Date.UTC(fin.getUTCFullYear() - PLAGES[etat.plage], fin.getUTCMonth(), fin.getUTCDate() + 1));
}

// --- Classes -------------------------------------------------------------------------------

const classe = (n) => etat.classes.find((c) => c.classe === n);
const couleurClasse = (n) => classe(n)?.couleur ?? "#c8c8c2";

function puceClasse(n, valeur) {
  if (!n) return el("span", { class: "classe" }, el("span", { class: "pastille", style: { background: "#c8c8c2" } }), "sans indice");
  return el("span", { class: "classe" },
    el("span", { class: "pastille", style: { background: couleurClasse(n) } }),
    `${n} – ${classe(n).libelle}`, valeur !== undefined ? ` (${nombre(valeur)})` : "");
}

const expressionClasse = () => [
  "match", ["coalesce", ["get", "classe"], 0],
  ...etat.classes.flatMap((c) => [c.classe, c.couleur]), "#c8c8c2",
];

function piecesClasses() {
  const s = etat.seuils;
  return etat.classes.map((c, i) => ({
    ...(i > 0 ? { gt: s[i - 1] } : {}), ...(i < s.length ? { lte: s[i] } : {}), color: c.couleur,
  }));
}

// --- Carte ---------------------------------------------------------------------------------

function initialiserCarte() {
  carte = new maplibregl.Map({
    container: "carte",
    style: {
      version: 8,
      sources: { ign: { type: "raster", tiles: [IGN], tileSize: 256, maxzoom: 18, attribution: "© IGN – Plan IGN" } },
      layers: [{ id: "ign", type: "raster", source: "ign", paint: { "raster-saturation": -0.3 } }],
    },
    center: [-1.3, 46.65], zoom: 8, attributionControl: { compact: true },
  });
  carte.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  return new Promise((resolve) => carte.on("load", () => {
    carte.addImage("carre", carreSdf(), { sdf: true });
    ajouterCouches();
    resolve();
  }));
}

function carreSdf() {
  // Carré en champ de distance (SDF) : se colore par donnée, avec un liseré (halo)
  const taille = 32, marge = 6, donnees = new Uint8Array(taille * taille * 4);
  for (let y = 0; y < taille; y++) {
    for (let x = 0; x < taille; x++) {
      const interieur = Math.min(x - marge, taille - 1 - marge - x, y - marge, taille - 1 - marge - y);
      const i = (y * taille + x) * 4;
      donnees.set([255, 255, 255, Math.max(0, Math.min(255, 192 + interieur * 24))], i);
    }
  }
  return { width: taille, height: taille, data: donnees };
}

function ajouterCouches() {
  const vide = { type: "FeatureCollection", features: [] };
  carte.addSource("zones", { type: "geojson", data: vide, promoteId: "zone_id" });
  carte.addSource("stations", { type: "geojson", data: vide, promoteId: "station_id" });
  carte.addLayer({
    id: "zones", type: "fill", source: "zones",
    paint: {
      "fill-color": expressionClasse(),
      "fill-opacity": ["case", ["boolean", ["feature-state", "survol"], false], 0.85, 0.68],
    },
  });
  carte.addLayer({
    id: "zones-contour", type: "line", source: "zones",
    paint: {
      "line-color": "#2d2d2b",
      "line-width": ["case", ["boolean", ["feature-state", "selection"], false], 3, 0.8],
    },
  });
  const pointsIndice = (source) => ({
    id: source, type: "circle", source: "stations",
    filter: ["all", ["==", ["get", "source"], source], ["!=", ["get", "classe"], null]],
    paint: {
      "circle-radius": 5.5,
      // Hors composite (mesure trop ancienne, D1) : anneau de couleur sur fond blanc
      "circle-color": ["case", ["==", ["get", "dans_composite"], false], "#ffffff", expressionClasse()],
      "circle-stroke-color": ["case", ["==", ["get", "dans_composite"], false], expressionClasse(), "#ffffff"],
      "circle-stroke-width": ["case", ["==", ["get", "dans_composite"], false], 2.2, 1.5],
    },
  });
  carte.addLayer(pointsIndice("piezo"));
  carte.addLayer(pointsIndice("hydro"));
  carte.addLayer({
    id: "retenue", type: "symbol", source: "stations",
    filter: ["all", ["==", ["get", "source"], "retenue"], ["!=", ["get", "remplissage_pct"], null]],
    layout: { "icon-image": "carre", "icon-size": 0.5, "icon-allow-overlap": true, "icon-ignore-placement": true },
    paint: {
      "icon-color": ["step", ["get", "remplissage_pct"], ...REMPLISSAGE.flatMap(([b, c], i) => (i === 0 ? [c] : [b, c]))],
      "icon-halo-color": "#ffffff", "icon-halo-width": 1.5,
    },
  });
  carte.addLayer({
    id: "onde", type: "circle", source: "stations",
    filter: ["all", ["==", ["get", "source"], "onde"], ["!=", ["get", "modalite"], null]],
    layout: { visibility: "none" },
    paint: {
      "circle-radius": 4.5,
      "circle-color": ["match", ["get", "modalite"], ...[...MODALITES].flatMap(([m, [, c]]) => [m, c]), "#c8c8c2"],
      "circle-stroke-color": "#5a3a1a", "circle-stroke-width": 0.8,
    },
  });

  const couchesStations = ["piezo", "hydro", "retenue", "onde"];
  let survolee = null;
  carte.on("mousemove", (e) => {
    const visibles = couchesStations.filter((c) => carte.getLayoutProperty(c, "visibility") !== "none");
    const [objet] = carte.queryRenderedFeatures(e.point, { layers: [...visibles, "zones"] });
    if (survolee !== null) carte.setFeatureState({ source: "zones", id: survolee }, { survol: false });
    survolee = null;
    if (!objet) { bulle.remove(); carte.getCanvas().style.cursor = ""; return; }
    carte.getCanvas().style.cursor = "pointer";
    if (objet.layer.id === "zones") {
      survolee = objet.properties.zone_id;
      carte.setFeatureState({ source: "zones", id: survolee }, { survol: true });
    }
    bulle.setLngLat(e.lngLat).setDOMContent(contenuBulle(objet)).addTo(carte);
  });
  carte.getCanvas().addEventListener("mouseleave", () => bulle.remove());
  carte.on("click", (e) => {
    const visibles = couchesStations.filter((c) => carte.getLayoutProperty(c, "visibility") !== "none");
    const [objet] = carte.queryRenderedFeatures(e.point, { layers: [...visibles, "zones"] });
    if (!objet) return;
    if (objet.layer.id === "zones") selectionner({ type: "zone", id: objet.properties.zone_id });
    else selectionner({ type: "station", id: objet.properties.station_id });
  });
}

function contenuBulle(objet) {
  const p = objet.properties;
  if (objet.layer.id === "zones") {
    return el("div", {}, el("div", { class: "bulle-titre" }, p.libelle),
      el("div", { class: "bulle-ligne" }, p.classe ? `Composite : ${p.classe} – ${classe(p.classe).libelle} (${nombre(p.valeur)})` : "Pas d'indice cette semaine"));
  }
  const lignes = [SOURCES[p.source]];
  if (p.source === "retenue") lignes.push(`Remplissage : ${pourcent(p.remplissage_pct)} le ${dateFr(p.date_releve)}`);
  else if (p.source === "onde") lignes.push(`${MODALITES.get(p.modalite)?.[0] ?? p.modalite} le ${dateFr(p.date_campagne)}`);
  else {
    lignes.push(`${p.indice === "ips" ? "IPS" : "Indice de débit"} : ${p.classe} – ${classe(p.classe).libelle} (${nombre(p.valeur)})`);
    if (p.dans_composite === false) lignes.push(`Hors composite : dernière mesure le ${dateFr(p.date_mesure)}`);
  }
  return el("div", {}, el("div", { class: "bulle-titre" }, p.libelle), ...lignes.map((l) => el("div", { class: "bulle-ligne" }, l)));
}

function ajusterEmprise(collection) {
  const coins = [Infinity, Infinity, -Infinity, -Infinity];
  const parcourir = (c) => (typeof c[0] === "number"
    ? (coins[0] = Math.min(coins[0], c[0]), coins[1] = Math.min(coins[1], c[1]),
       coins[2] = Math.max(coins[2], c[0]), coins[3] = Math.max(coins[3], c[1]))
    : c.forEach(parcourir));
  collection.features.forEach((f) => parcourir(f.geometry.coordinates));
  const legende = document.getElementById("legende").offsetWidth;
  carte.fitBounds([[coins[0], coins[1]], [coins[2], coins[3]]], { padding: { top: 30, bottom: 30, right: 50, left: legende + 30 }, duration: 0 });
}

function legende() {
  const bloc = document.getElementById("legende");
  const case_ = (couche, texte, coche) => el("label", {},
    el("input", { type: "checkbox", checked: coche, onchange: (e) => carte.setLayoutProperty(couche, "visibility", e.target.checked ? "visible" : "none") }),
    texte);
  bloc.replaceChildren(
    el("h3", {}, "Classes (composite et stations)"),
    el("ul", {}, etat.classes.map((c) => el("li", {}, el("span", { class: "pastille", style: { background: c.couleur } }), `${c.classe} – ${c.libelle}`))),
    el("ul", {}, el("li", {}, el("span", { class: "pastille rond creux", style: { borderColor: "#7a7974" } }), "Piézomètre hors composite (mesure ancienne)")),
    el("h3", {}, "Retenues : remplissage"),
    el("ul", {}, REMPLISSAGE.map(([b, c], i) => el("li", {}, el("span", { class: "pastille", style: { background: c } }),
      i < REMPLISSAGE.length - 1 ? `${b} à ${REMPLISSAGE[i + 1][0]}\u00a0%` : `${b}\u00a0% et plus`))),
    el("h3", {}, "Couches"),
    case_("piezo", "Piézomètres (IPS)", true),
    case_("hydro", "Stations de débit", true),
    case_("retenue", "Retenues (% de remplissage)", true),
    case_("onde", "Stations ONDE (dernière observation)", false),
    el("ul", { class: "legende-onde" }, [...MODALITES.values()].map(([libelle, c]) => el("li", {},
      el("span", { class: "pastille rond", style: { background: c } }), libelle))),
  );
}

// --- Chargement d'une semaine --------------------------------------------------------------

async function chargerSemaine(semaine) {
  etat.semaine = semaine;
  document.getElementById("semaine").value = semaine;
  const index = etat.semaines.indexOf(semaine);
  document.getElementById("semaine-suivante").disabled = index <= 0;
  document.getElementById("semaine-precedente").disabled = index === etat.semaines.length - 1;
  document.getElementById("panneau").style.opacity = 0.55;
  try {
    Object.assign(etat, await source.semaine(semaine));
    const { zones, stations } = etat;
    carte.getSource("zones").setData(zones);
    carte.getSource("stations").setData(stations);
    tuiles();
    await afficherSelection();
    alerte("");
  } catch (erreur) {
    alerte(`Chargement impossible : ${erreur.message}`);
  } finally {
    document.getElementById("panneau").style.opacity = 1;
  }
  memoriser();
}

function tuiles() {
  const { synthese } = etat;
  const zones = synthese.composite.zones;
  const stations = Object.fromEntries(synthese.stations.map((s) => [s.indice, s]));
  const tuile = (libelle, valeur, detail) => el("div", { class: "tuile" },
    el("div", { class: "tuile-libelle" }, libelle), el("div", { class: "tuile-valeur" }, valeur),
    el("div", { class: "tuile-detail" }, detail));
  const debit = stations.debit;
  const debitsSecs = debit ? (debit.repartition["1"] ?? 0) + (debit.repartition["2"] ?? 0) : null;
  const total = synthese.retenues.total, enveloppe = synthese.retenues.enveloppe;
  const onde = synthese.onde, observees = onde.reduce((s, o) => s + o.n_stations, 0);
  const sansEcoulement = onde.reduce((s, o) => s + o.valeur * o.n_stations, 0);
  const derniereCampagne = onde.map((o) => o.date_campagne).sort().at(-1);
  document.getElementById("tuiles").replaceChildren(
    tuile("Zones très sèches ou sèches (classes 1-2)", `${synthese.composite.zones_seches} / ${zones.length}`,
      `du ${dateFr(synthese.debut)} au ${dateFr(synthese.fin)}`),
    tuile("Retenues d'eau potable", total ? pourcent(total.remplissage_pct) : "—",
      enveloppe && total ? `médiane ${enveloppe.periode_ref} : ${pourcent(enveloppe.mediane)} · min ${pourcent(enveloppe.minimum)}` : "pas de relevé cette semaine"),
    tuile("Stations de débit en classe 1-2", debit ? `${debitsSecs} / ${debit.n}` : "—", "débit moyen sur 7 jours"),
    tuile("Piézomètres au composite", stations.ips ? `${stations.ips.au_composite} / ${stations.ips.n}` : "—",
      "les autres ont une mesure trop ancienne"),
    tuile("Stations ONDE sans écoulement", observees ? pourcent((100 * sansEcoulement) / observees, 0) : "—",
      derniereCampagne ? `dernière campagne le ${dateFr(derniereCampagne)}` : "hors période de suivi"),
  );
}

// --- Panneau : synthèse, zone, station -----------------------------------------------------

function selectionner(selection) {
  if (etat.selection?.type === "zone") carte.setFeatureState({ source: "zones", id: etat.selection.id }, { selection: false });
  etat.selection = selection;
  afficherSelection();
  memoriser();
}

async function afficherSelection() {
  const panneau = document.getElementById("panneau");
  panneau.querySelectorAll(".graphique").forEach((g) => echarts.getInstanceByDom(g)?.dispose());
  const { selection } = etat;
  if (selection?.type === "zone") carte.setFeatureState({ source: "zones", id: selection.id }, { selection: true });
  try {
    const blocs = !selection ? panneauSynthese()
      : selection.type === "zone" ? await panneauZone(selection.id) : await panneauStation(selection.id);
    panneau.replaceChildren(...blocs.filter(Boolean));
  } catch (erreur) {
    panneau.replaceChildren(el("p", { class: "note" }, `Données indisponibles : ${erreur.message}`), retour());
  }
}

const retour = () => el("button", { class: "lien", onclick: () => selectionner(null) }, "← Synthèse de la semaine");

function panneauSynthese() {
  const { synthese } = etat;
  const lignes = synthese.composite.zones.map((z) => el("li", {}, el("button", { onclick: () => selectionner({ type: "zone", id: z.zone_id }) },
    el("span", {}, z.libelle), puceClasse(z.classe, z.valeur),
    z.partiel ? el("span", { class: "detail" }, `Composante absente : ${z.manquantes.map((m) => COMPOSANTES_ABSENTES[m] ?? m).join(", ")}`) : null)));
  const blocs = [
    el("h2", {}, `Semaine ${synthese.semaine}`),
    el("p", { class: "meta" }, `Du ${dateFr(synthese.debut)} au ${dateFr(synthese.fin)} · cliquer une zone ou une station pour ses séries`),
    el("h3", {}, "Zones, de la plus sèche à la plus humide (indice composite)"),
    el("ul", { class: "liste-zones" }, lignes),
  ];
  const { total, enveloppe } = synthese.retenues;
  if (total) {
    blocs.push(el("h3", {}, "Retenues d'eau potable (hors composite)"),
      el("p", {}, `${pourcent(total.remplissage_pct)} de remplissage au ${dateFr(total.date)} (${total.n_retenues} retenues, ${nombre(total.volume_m3 / 1e6, 1)} Mm³ sur ${nombre(total.capacite_m3 / 1e6, 1)}).`),
      enveloppe ? el("p", { class: "note" }, `Même semaine en ${enveloppe.periode_ref} : minimum ${pourcent(enveloppe.minimum)}, médiane ${pourcent(enveloppe.mediane)}, maximum ${pourcent(enveloppe.maximum)}.`) : null);
  }
  if (synthese.onde.length) {
    blocs.push(el("h3", {}, "Dernière campagne ONDE de l'année (hors composite)"),
      tableau(["Zone", "Campagne", "Sans écoulement", "Stations"],
        synthese.onde.map((o) => [o.libelle, dateFr(o.date_campagne), pourcent(100 * o.valeur, 0), o.n_stations]), [2, 3]));
  }
  return blocs;
}

function outilsPlage(rafraichir) {
  return el("div", { class: "outils" }, el("span", { class: "meta" }, "Période :"),
    Object.keys(PLAGES).map((p) => el("button", { class: "bouton", "aria-pressed": String(p === etat.plage),
      onclick: () => { etat.plage = p; rafraichir(); } }, p)));
}

function tableau(entetes, lignes, colonnesNombres = []) {
  return el("div", { class: "tableau" }, el("table", {},
    el("thead", {}, el("tr", {}, entetes.map((t, i) => el("th", { class: colonnesNombres.includes(i) ? "nombre" : null }, t)))),
    el("tbody", {}, lignes.map((l) => el("tr", {}, l.map((v, i) => el("td", { class: colonnesNombres.includes(i) ? "nombre" : null }, v)))))));
}

function blocGraphique(titre, construire, lignesTableau, entetes, colonnesNombres) {
  // Chaque graphique a son tableau (accessibilité : aucune valeur réservée à l'info-bulle)
  const zone = el("div", { class: "graphique" });
  let ouvert = false;
  const conteneurTableau = el("div");
  const bouton = el("button", { class: "bouton", "aria-pressed": "false", onclick: () => {
    ouvert = !ouvert;
    bouton.setAttribute("aria-pressed", String(ouvert));
    conteneurTableau.replaceChildren(...(ouvert ? [tableau(entetes, lignesTableau().slice().reverse(), colonnesNombres)] : []));
  } }, "Tableau");
  requestAnimationFrame(() => construire(echarts.init(zone, null, { renderer: "svg" })));
  return [el("div", { class: "outils" }, el("h3", { style: { margin: 0 } }, titre), el("span", { class: "espace" }), bouton), zone, conteneurTableau];
}

const axeTemps = () => ({
  type: "time", axisLine: { lineStyle: { color: GRIS.axe } }, splitLine: { show: false },
  axisLabel: { color: GRIS.texte, hideOverlap: true, formatter: etiquetteDate, rich: { annee: { fontWeight: 600, color: GRIS.texte } } },
});
const axeIndice = () => ({
  type: "value", min: -3, max: 3, interval: 1,
  axisLabel: { color: GRIS.texte }, splitLine: { lineStyle: { color: GRIS.grille } },
});
const seuilsEtNormale = () => ({
  markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: GRIS.axe, width: 1, type: "solid" }, data: etat.seuils.map((s) => ({ yAxis: s })) },
  markArea: { silent: true, itemStyle: { color: "rgba(77,175,74,0.08)" }, data: [[{ yAxis: etat.seuils[2] }, { yAxis: etat.seuils[3] }]] },
});
const bulleAxe = (lignes) => ({
  trigger: "axis", axisPointer: { type: "line", lineStyle: { color: "#9a9993" } },
  formatter: (params) => `<b>${echapper(dateFr(params[0].value[0]))}</b><br>${lignes(params).join("<br>")}`,
});
const libelleIndice = (v) => {
  const i = etat.seuils.findIndex((s) => v <= s);
  const c = etat.classes[i === -1 ? etat.classes.length - 1 : i];
  return `${nombre(v)} (${c.classe} – ${echapper(c.libelle)})`;
};

function grapheIndice(instance, points, nom) {
  // Semaines dont la mesure est trop ancienne (D1) : tracé gris séparé, hors composite
  const anciennes = points.some((p) => p.dans_composite === false);
  const valeur = (garder) => points.map((p) => [dimancheDe(p.semaine), garder(p) ? p.valeur : null]);
  const series = [{ name: nom, type: "line", data: valeur((p) => p.dans_composite !== false), showSymbol: false, lineStyle: { width: 2 }, ...seuilsEtNormale() }];
  if (anciennes) {
    series.push({ name: `${nom} (mesure ancienne, hors composite)`, type: "line", data: valeur((p) => p.dans_composite === false),
      showSymbol: false, color: "#b5b4ae", lineStyle: { width: 2 } });
  }
  instance.setOption({
    animation: false, grid: { left: 36, right: 14, top: anciennes ? 34 : 12, bottom: 26 },
    legend: anciennes ? { top: 0, left: 0, icon: TRAIT, itemWidth: 14, textStyle: { color: GRIS.texte }, data: series.map((s) => s.name) } : undefined,
    xAxis: axeTemps(), yAxis: axeIndice(),
    visualMap: { show: false, type: "piecewise", dimension: 1, seriesIndex: 0, pieces: piecesClasses() },
    tooltip: bulleAxe((params) => params.filter((p) => p.value[1] !== null && p.value[1] !== undefined)
      .map((p) => `${echapper(p.seriesName)} : ${libelleIndice(p.value[1])}`)),
    series,
  });
}

function grapheComposantes(instance, series) {
  const indices = Object.keys(series);
  instance.setOption({
    animation: false, grid: { left: 36, right: 14, top: 34, bottom: 26 },
    legend: { top: 0, left: 0, icon: TRAIT, itemWidth: 14, textStyle: { color: GRIS.texte } },
    xAxis: axeTemps(), yAxis: axeIndice(),
    tooltip: bulleAxe((params) => params.map((p) => `<span style="display:inline-block;width:10px;height:2px;background:${p.color};vertical-align:middle;margin-right:6px"></span>${echapper(p.seriesName)} : <b>${nombre(p.value[1])}</b>`)),
    series: indices.map((indice, i) => ({
      name: NOMS_INDICES[indice], type: "line", showSymbol: false, color: COULEURS_COMPOSANTES[indice], lineStyle: { width: 2 },
      data: series[indice].map((p) => [dimancheDe(p.semaine), p.valeur]), ...(i === 0 ? seuilsEtNormale() : {}),
    })),
  });
}

async function panneauZone(zoneId) {
  const fin = etat.semaine, debut = semaineDe(debutPlage());
  const [composite, spi, ips, debit, onde] = await Promise.all([
    ...["composite", "spi_3", "ips", "debit"].map((indice) => source.serieZone(zoneId, indice, debut, fin)),
    source.serieZone(zoneId, "onde", `${fin.slice(0, 4)}-W01`, fin),
  ]);
  const zone = etat.zones.features.find((f) => f.properties.zone_id === zoneId).properties;
  const ponderations = zone.ponderations || {};
  const lignesComposantes = ["spi_3", "ips", "debit"].filter((i) => ponderations[i] > 0).map((i) => {
    const c = zone.composantes?.[i];
    return [NOMS_INDICES[i], c ? nombre(c.valeur) : "absent", nombre(ponderations[i]), c ? nombre(c.poids_applique) : "—"];
  });
  const series = Object.fromEntries([["spi_3", spi], ["ips", ips], ["debit", debit]].filter(([i]) => ponderations[i] > 0).map(([i, s]) => [i, s.points]));
  const blocs = [
    el("div", { class: "panneau-entete" }, el("div", {}, el("h2", {}, zone.libelle), el("p", { class: "meta" }, `Semaine ${etat.semaine}`)), retour()),
    el("p", {}, puceClasse(zone.classe, zone.valeur ?? undefined)),
    el("h3", {}, "Composantes de la semaine"),
    tableau(["Indice", "Valeur", "Poids prévu", "Poids appliqué"], lignesComposantes, [1, 2, 3]),
    zone.partiel ? el("p", { class: "note" }, "Composante absente : son poids est réparti sur les autres (méthodologie §6.4).") : null,
    zone.valeur_brute != null ? el("p", { class: "note" }, `Moyenne pondérée des composantes : ${nombre(zone.valeur_brute)}. Elle est reclassée parmi les semaines de référence de la zone (1991-2020) pour donner la valeur du composite, ${nombre(zone.valeur)} (méthodologie D10).`) : null,
    outilsPlage(afficherSelection),
    ...blocGraphique("Indice composite", (g) => grapheIndice(g, composite.points, "Composite"),
      () => composite.points.map((p) => [p.semaine, nombre(p.valeur), `${p.classe} – ${classe(p.classe).libelle}`]), ["Semaine", "Valeur", "Classe"], [1]),
    ...blocGraphique("Composantes (valeurs standardisées)", (g) => grapheComposantes(g, series),
      () => composite.points.map((p) => [p.semaine, ...Object.keys(series).map((i) => nombre(series[i].find((x) => x.semaine === p.semaine)?.valeur))]),
      ["Semaine", ...Object.keys(series).map((i) => NOMS_INDICES[i])], [1, 2, 3]),
    el("p", { class: "note" }, "Bande verte : normale (classe 4). Traits fins : seuils des classes."),
  ];
  if (onde.points.length) {
    blocs.push(...blocGraphique(`ONDE ${fin.slice(0, 4)} : part des stations sans écoulement`, (g) => g.setOption({
      animation: false, grid: { left: 40, right: 14, top: 12, bottom: 26 },
      xAxis: { type: "category", data: onde.points.map((p) => dateFr(p.detail.date_campagne)), axisLabel: { color: GRIS.texte }, axisLine: { lineStyle: { color: GRIS.axe } } },
      yAxis: { type: "value", min: 0, max: 100, axisLabel: { color: GRIS.texte, formatter: "{value} %" }, splitLine: { lineStyle: { color: GRIS.grille } } },
      tooltip: { trigger: "item", formatter: (p) => `${echapper(p.name)} : <b>${nombre(p.value, 0)} %</b>` },
      series: [{ type: "bar", data: onde.points.map((p) => 100 * p.valeur), barMaxWidth: 24, color: "#d95f0e", itemStyle: { borderRadius: [4, 4, 0, 0] } }],
    }), () => onde.points.map((p) => [dateFr(p.detail.date_campagne), `${nombre(100 * p.valeur, 0)} %`, p.n_stations]), ["Campagne", "Sans écoulement", "Stations"], [1, 2]));
  }
  return blocs;
}

function enveloppeSur(dates, enveloppe) {
  // Enveloppe journalière (mois ou semaine ISO de chaque date), pour la bande min-max
  const parPeriode = new Map(enveloppe.points.map((p) => [p.periode, p]));
  return dates.map((d) => {
    const p = parPeriode.get(enveloppe.pas === "mois" ? d.getUTCMonth() + 1 : numeroSemaine(d));
    return p ? [d, p.minimum, p.mediane, p.maximum] : [d, null, null, null];
  });
}

function grapheMesure(instance, chronique, enveloppe, debut, fin) {
  const unite = chronique.unite;
  const pas = chronique.grandeur === "remplissage_pct" ? 7 : 1;
  const dates = [];
  for (let t = Math.max(debut.getTime(), chronique.points.length ? Date.parse(chronique.points[0].date) : debut.getTime()); t <= fin.getTime(); t += pas * 86400000) dates.push(new Date(t));
  const env = enveloppeSur(dates, enveloppe);
  // Débits : échelle logarithmique, pour lire les étiages autant que les crues
  const log = chronique.grandeur === "qmj_ls";
  const affiche = (v) => (v === null || !log ? v : Math.max(v, PLANCHER_DEBIT));
  const mesures = chronique.points.map((p) => [Date.parse(p.date), affiche(p.valeur)]);
  const brutes = new Map(chronique.points.map((p) => [p.date, p.valeur]));
  const parDate = new Map(env.map((e) => [iso(e[0]), e]));
  instance.setOption({
    animation: false, grid: { left: 52, right: 14, top: 34, bottom: 26 },
    legend: { top: 0, left: 0, textStyle: { color: GRIS.texte }, itemWidth: 14, data: [
      { name: "Mesure", icon: TRAIT }, { name: "Médiane de référence", icon: TRAIT }, { name: "Min–max de référence", icon: "rect" }] },
    xAxis: axeTemps(),
    yAxis: { type: log ? "log" : "value", scale: chronique.grandeur === "niveau_ngf", min: chronique.grandeur === "remplissage_pct" ? 0 : undefined,
      axisLabel: { color: GRIS.texte, formatter: (v) => nombre(v) }, splitLine: { lineStyle: { color: GRIS.grille } } },
    tooltip: bulleAxe((params) => {
      const jour = iso(new Date(params[0].value[0]));
      const e = parDate.get(jour);
      return [
        brutes.has(jour) ? `Mesure : <b>${nombre(brutes.get(jour))} ${unite}</b>` : "Pas de mesure",
        e && e[2] !== null ? `Référence : médiane ${nombre(e[2])}, min ${nombre(e[1])}, max ${nombre(e[3])} ${unite}` : "",
      ].filter(Boolean);
    }),
    series: [
      { name: "bas", type: "line", data: env.map((e) => [e[0], affiche(e[1])]), stack: "env", lineStyle: { opacity: 0 }, showSymbol: false, silent: true, tooltip: { show: false } },
      { name: "Min–max de référence", type: "line", data: env.map((e) => [e[0], e[1] === null ? null : affiche(e[3]) - affiche(e[1])]), stack: "env", lineStyle: { opacity: 0 }, areaStyle: { color: GRIS.enveloppe }, showSymbol: false, silent: true, color: "#d6d5cf" },
      { name: "Médiane de référence", type: "line", data: env.map((e) => [e[0], affiche(e[2])]), lineStyle: { width: 1, color: GRIS.mediane }, color: GRIS.mediane, showSymbol: false },
      { name: "Mesure", type: "line", data: mesures, lineStyle: { width: 2 }, color: "#2a78d6", showSymbol: mesures.length < 60, symbolSize: 5 },
    ],
  });
}

async function panneauStation(stationId) {
  const fin = dimancheDe(etat.semaine), debut = debutPlage();
  const serie = await source.serieStation(stationId, iso(debut), iso(fin));
  const p = serie.station.properties;
  const actuelle = etat.stations.features.find((f) => f.properties.station_id === stationId)?.properties ?? {};
  const blocs = [
    el("div", { class: "panneau-entete" }, el("div", {}, el("h2", {}, p.libelle),
      el("p", { class: "meta" }, `${SOURCES[p.source]} · ${p.code}${p.en_service ? "" : " · hors service"}`)), retour()),
  ];
  if (p.source === "piezo" || p.source === "hydro") {
    blocs.push(el("p", {}, actuelle.classe ? puceClasse(actuelle.classe, actuelle.valeur) : "Pas d'indice cette semaine"));
    if (actuelle.date_mesure) {
      blocs.push(el("p", { class: "note" }, `Dernière mesure retenue le ${dateFr(actuelle.date_mesure)}${actuelle.dans_composite === false ? " : trop ancienne, hors composite" : ""}${actuelle.hors_reference ? " · normale établie hors de 1991-2020" : ""}.`));
    }
  }
  blocs.push(outilsPlage(afficherSelection));
  if (p.source === "onde") {
    blocs.push(el("h3", {}, "Observations"), serie.chronique.points.length
      ? tableau(["Date", "Écoulement", "Campagne"], serie.chronique.points.slice().reverse().map((o) => [dateFr(o.date), MODALITES.get(o.valeur)?.[0] ?? o.valeur, o.type_campagne]))
      : el("p", { class: "note" }, "Aucune observation sur la période."));
    return blocs;
  }
  const titres = { niveau_ngf: "Niveau de la nappe", qmj_ls: "Débit journalier", remplissage_pct: "Remplissage" };
  const unite = serie.chronique.unite;
  blocs.push(...blocGraphique(`${titres[serie.chronique.grandeur]} (${unite}) et normale`,
    (g) => grapheMesure(g, serie.chronique, serie.enveloppe, debut, fin),
    () => serie.chronique.points.map((m) => [dateFr(m.date), nombre(m.valeur)]), ["Date", `Mesure (${unite})`], [1]));
  if (!serie.chronique.points.length) blocs.push(el("p", { class: "note" }, "Aucune mesure sur la période : élargir la période."));
  blocs.push(el("p", { class: "note" }, `Normale : ${serie.enveloppe.points[0]?.periode_ref ?? "—"}, par ${serie.enveloppe.pas ?? "—"} (bande grise : minimum et maximum de la référence).`
    + (p.source === "hydro" ? ` Échelle logarithmique : un débit inférieur à ${PLANCHER_DEBIT} l/s s'affiche à ${PLANCHER_DEBIT} l/s.` : "")));
  if (serie.indices.length) {
    const nom = p.source === "piezo" ? "IPS" : "Indice de débit";
    blocs.push(...blocGraphique(`${nom} hebdomadaire`, (g) => grapheIndice(g, serie.indices, nom),
      () => serie.indices.map((i) => [i.semaine, nombre(i.valeur), `${i.classe} – ${classe(i.classe).libelle}`]), ["Semaine", "Valeur", "Classe"], [1]));
  }
  return blocs;
}

// --- Adresse de la page : semaine et sélection (lien partageable) --------------------------

function memoriser() {
  const parametres = new URLSearchParams({ semaine: etat.semaine });
  if (etat.selection) parametres.set(etat.selection.type, etat.selection.id);
  history.replaceState(null, "", `#${parametres}`);
}

function lireAdresse() {
  const parametres = new URLSearchParams(location.hash.slice(1));
  const zone = parametres.get("zone"), station = parametres.get("station");
  etat.selection = zone ? { type: "zone", id: zone } : station ? { type: "station", id: station } : null;
  const semaine = parametres.get("semaine");
  return etat.semaines.includes(semaine) ? semaine : etat.semaines[0];
}

function piedDePage(accueil) {
  // Version publique : avertissement permanent ; dans tous les cas, sources citées
  const bandeau = document.getElementById("bandeau");
  bandeau.hidden = !(STATIQUE && accueil.avertissement);
  bandeau.textContent = accueil.avertissement ?? "";
  document.getElementById("lien-api").hidden = STATIQUE;
  document.getElementById("sources").textContent = (accueil.sources ?? []).length ? `Sources : ${accueil.sources.join(" · ")}.` : "";
}

// --- Démarrage -----------------------------------------------------------------------------

async function demarrer() {
  try {
    const [accueil, classes, semaines] = await source.generalites();
    Object.assign(etat, { territoire: accueil.territoire, version: accueil.version_methodo, classes: classes.classes, seuils: classes.seuils, semaines: semaines.semaines });
    piedDePage(accueil);
  } catch (erreur) {
    alerte(`API injoignable : ${erreur.message}`);
    return;
  }
  document.getElementById("titre").textContent = `Observatoire de la sécheresse – ${etat.territoire}`;
  document.title = `Sécheresse – ${etat.territoire}`;
  document.getElementById("pied-methode").textContent = `Méthode ${etat.version} · dernière semaine calculée ${etat.semaines[0]}`;
  const champ = document.getElementById("semaine");
  champ.min = etat.semaines.at(-1);
  champ.max = etat.semaines[0];
  const decaler = (pas) => {
    const i = etat.semaines.indexOf(etat.semaine) + pas;
    if (i >= 0 && i < etat.semaines.length) chargerSemaine(etat.semaines[i]);
  };
  document.getElementById("semaine-precedente").addEventListener("click", () => decaler(1));
  document.getElementById("semaine-suivante").addEventListener("click", () => decaler(-1));
  document.getElementById("semaine-derniere").addEventListener("click", () => chargerSemaine(etat.semaines[0]));
  champ.addEventListener("change", () => {
    if (etat.semaines.includes(champ.value)) chargerSemaine(champ.value);
    else alerte(`Pas d'indice pour la semaine « ${champ.value} » (de ${champ.min} à ${champ.max}).`);
  });
  document.getElementById("choix-semaine").addEventListener("submit", (e) => e.preventDefault());

  legende();
  await initialiserCarte();
  await chargerSemaine(lireAdresse());
  ajusterEmprise(etat.zones);
  window.addEventListener("resize", () => document.querySelectorAll(".graphique").forEach((g) => echarts.getInstanceByDom(g)?.resize()));
}

demarrer();
