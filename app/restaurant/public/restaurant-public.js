"use strict";
const publicElement = id => document.getElementById(id);
const days = {monday:"Esmaspäev",tuesday:"Teisipäev",wednesday:"Kolmapäev",thursday:"Neljapäev",friday:"Reede",saturday:"Laupäev",sunday:"Pühapäev"};
function publicStatus(id, text, error=false) {
  const node = publicElement(id); node.textContent = text; node.className = "load-status" + (error ? " error" : "");
}
function renderPublicRestaurant(data) {
  const venue = data.restaurant;
  if (data.synthetic !== true || data.business_type !== "restaurant" || !venue || !Array.isArray(venue.tables) || !Array.isArray(venue.menu)) throw new Error("restaurant_unavailable");
  publicElement("property-description").textContent = venue.description.et;
  publicElement("allergy-notice").textContent = venue.allergy_notice.et;
  publicElement("table-grid").replaceChildren();
  for (const table of venue.tables) {
    const card=document.createElement("article"), title=document.createElement("h3"), capacity=document.createElement("p"), link=document.createElement("a");
    card.className="table-card"; title.textContent=table.name; capacity.textContent=`Kuni ${table.capacity} külalist`;
    link.className="text-link"; link.href="https://robot.arleserver.cfd/?book=table"; link.textContent="Kontrolli saadavust ↗";
    link.setAttribute("aria-label",`${table.name}: kontrolli demo saadavust`);
    card.append(title,capacity,link); publicElement("table-grid").append(card);
  }
  publicStatus("tables-status","Demolaudade mahutavus, mitte hetke saadavus.");
  publicElement("menu-list").replaceChildren();
  for (const dish of venue.menu) {
    const item=document.createElement("li"), title=document.createElement("h3"), note=document.createElement("p");
    title.textContent=dish.name.et; note.textContent="Fiktiivne demoroog. Allergiaohutus ei ole kinnitatud.";
    item.append(title,note); publicElement("menu-list").append(item);
  }
  publicStatus("menu-status","Fiktiivne demomenüü. Tellimusi ega makseid ei võeta vastu.");
  publicElement("opening-hours").replaceChildren();
  for (const [day,hours] of Object.entries(venue.opening_hours)) {
    const row=document.createElement("li"), name=document.createElement("span"), time=document.createElement("span");
    name.textContent=days[day] || day; time.textContent=hours ? `${hours.start}–${hours.end}` : "Suletud";
    row.append(name,time); publicElement("opening-hours").append(row);
  }
  publicElement("hours-status").textContent="Tallinna ajavöönd. Laua saadavust kontrollitakse eraldi.";
  publicElement("rules-list").replaceChildren();
  for (const text of [venue.policies.et,`Laua kasutusaeg: ${venue.reservation_duration_minutes} minutit.`,`Suurim seltskond: ${venue.maximum_party_size} külalist, lapsed kaasa arvatud.`,`Broneerimine kuni ${venue.advance_days} päeva ette.`]) {
    const row=document.createElement("li"); row.textContent=text; publicElement("rules-list").append(row);
  }
  publicStatus("rules-status","Reeglid restorani kinnitatud demokataloogist.");
}
async function loadPublicRestaurant() {
  const controller=new AbortController(), deadline=setTimeout(()=>controller.abort(),15000);
  try {
    const response=await fetch("/api/public/restaurant",{signal:controller.signal,cache:"no-store",credentials:"omit"});
    if (!response.ok) throw new Error("restaurant_unavailable");
    renderPublicRestaurant(await response.json());
  } catch (_) {
    for (const id of ["table-grid","menu-list","rules-list","opening-hours"]) publicElement(id).replaceChildren();
    for (const id of ["tables-status","menu-status","rules-status"]) publicStatus(id,"Restorani kataloogi ei saanud laadida. Saadavus pole kinnitatud; proovi hiljem uuesti.",true);
    publicElement("hours-status").textContent="Lahtiolekuaegu ei saanud kontrollida.";
    publicElement("allergy-notice").textContent="Allergiaohutus ei ole kinnitatud.";
  } finally { clearTimeout(deadline); }
}
loadPublicRestaurant();
