"use strict";
const hotelElement=id=>document.getElementById(id);
const dayLabels={monday:"Esmaspäev",tuesday:"Teisipäev",wednesday:"Kolmapäev",thursday:"Neljapäev",friday:"Reede",saturday:"Laupäev",sunday:"Pühapäev"};
function hotelStatus(id,message,error=false){const element=hotelElement(id);element.textContent=message;element.className="load-status"+(error?" error":"");}
async function publicData(path){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
  try{const response=await fetch(path,{signal:controller.signal,cache:"no-store",credentials:"omit"});if(!response.ok)throw new Error("public_read_unavailable");return await response.json();}
  finally{clearTimeout(timeout);}
}
function renderRestaurantTables(items){
  hotelElement("table-grid").replaceChildren();
  for(const table of items){
    const card=document.createElement("article"),title=document.createElement("h3"),capacity=document.createElement("p"),link=document.createElement("a");
    card.className="table-card";title.textContent=table.name;capacity.textContent="Kuni "+table.capacity+" inimest";
    link.className="text-link";link.href="https://robot.arleserver.cfd/?book=table";link.textContent="Kontrolli saadavust ↗";link.setAttribute("aria-label",table.name+": kontrolli demo saadavust");
    card.append(title,capacity,link);hotelElement("table-grid").append(card);
  }
  hotelStatus("tables-status",items.length?"Füüsilised demolaudade kohad kataloogist. Saadavus kontrollitakse eraldi.":"Laudade kataloog on tühi; saadavus pole kinnitatud.",!items.length);
}
function renderRestaurantMenu(menu){
  hotelElement("menu-list").replaceChildren();
  for(const entry of menu){
    const item=document.createElement("li"),name=document.createElement("h3"),description=document.createElement("p");
    name.textContent=entry.name_et || entry.name;description.textContent=entry.description_et || entry.description || "";
    item.append(name,description);hotelElement("menu-list").append(item);
  }
  hotelStatus("menu-status",menu.length?"Fiktiivne demomenüü. Tellimusi ega makseid ei võeta vastu.":"Demomenüü andmed pole praegu saadaval.",!menu.length);
}
function renderRestaurantRules(rules){
  const labels={timezone:"Ajavöönd",opening_time:"Avatud alates",closing_time:"Suletud alates",duration_minutes:"Laua kasutusaeg (min)",min_party_size:"Vähim inimeste arv",max_party_size:"Suurim inimeste arv",horizon_days:"Broneerimine ette (päeva)",combine_tables:"Lauad ühendatavad",children_count_toward_party_size:"Lapsed arvestatakse inimeste hulka"};
  hotelElement("rules-list").replaceChildren();
  for(const [key,value] of Object.entries(rules || {})){
    if(!["string","number","boolean"].includes(typeof value))continue;
    const item=document.createElement("li");item.textContent=`${labels[key] || key}: ${typeof value==="boolean"?value?"jah":"ei":value}`;hotelElement("rules-list").append(item);
  }
  hotelStatus("rules-status",hotelElement("rules-list").children.length?"Reeglid restorani kataloogist. Kõik ajad on Tallinna ajavööndis.":"Restorani reegleid ei saanud kontrollida.",!hotelElement("rules-list").children.length);
}
function renderOpeningHours(property){
  const hours=property.opening_hours || {};
  hotelElement("opening-hours").replaceChildren();
  const rules=property.restaurant_rules;
  if(rules?.opening_time && rules?.closing_time){
    const row=document.createElement("li"),name=document.createElement("span"),time=document.createElement("span");
    name.textContent="Iga päev";time.textContent=`${rules.opening_time}–${rules.closing_time}`;row.append(name,time);hotelElement("opening-hours").append(row);
    hotelElement("hours-status").textContent="Ajavöönd: "+(property.timezone || "Europe/Tallinn")+". Kogu laua kasutusaeg peab jääma lahtiolekuaega.";
    return;
  }
  const entries=Array.isArray(hours)?hours.map(item=>[item.day,item]):Object.entries(hours);
  for(const [day,value] of entries){
    const row=document.createElement("li"),name=document.createElement("span"),time=document.createElement("span");name.textContent=dayLabels[day] || value?.label || day;
    if(value && value.start && value.end){
      let start=value.start;const intervals=[];
      for(const pause of [...(value.breaks || [])].sort((a,b)=>a.start.localeCompare(b.start))){if(pause.start>start)intervals.push(`${start}–${pause.start}`);start=pause.end;}
      if(start<value.end)intervals.push(`${start}–${value.end}`);time.textContent=intervals.join(", ");
    }else time.textContent="Suletud";
    row.append(name,time);hotelElement("opening-hours").append(row);
  }
  hotelElement("hours-status").textContent=entries.length?"Ajavöönd: "+(property.timezone || "Europe/Tallinn")+". Laua saadavus kontrollitakse eraldi.":"Lahtiolekuaegade andmed pole praegu saadaval.";
}
function renderRestaurantProperty(data){
  const property=data.property || {},phone=data.phone || {};
  if(property.description_et)hotelElement("property-description").textContent=property.description_et+" Kõik broneeringud on sünteetilised.";
  const number=phone.number;
  if(phone.configured===true && /^\+[1-9]\d{6,14}$/.test(number || "")){
    hotelElement("phone-number").href="tel:"+number;hotelElement("phone-number").textContent=number;hotelElement("phone-number").hidden=false;
    hotelElement("phone-status").textContent="Seadistatud demonumber. Telefonikõne valmisolekut kontrollib operaator; veebis saad proovida teksti või mikrofoniga.";
  }else{hotelElement("phone-number").hidden=true;hotelElement("phone-number").removeAttribute("href");hotelElement("phone-number").textContent="";hotelElement("phone-status").textContent="Demonumber pole seadistatud. Veebis saad proovida teksti või mikrofoniga.";}
  renderOpeningHours(property);
  if(Array.isArray(data.menu))renderRestaurantMenu(data.menu);
  if(property.restaurant_rules || data.rules)renderRestaurantRules(property.restaurant_rules || data.rules);
  hotelElement("faq-list").replaceChildren();
  for(const entry of data.faq || []){const details=document.createElement("details"),summary=document.createElement("summary"),answer=document.createElement("p");summary.textContent=entry.question_et;answer.textContent=entry.answer_et;details.append(summary,answer);hotelElement("faq-list").append(details);}
  if(!data.faq?.length){const note=document.createElement("p");note.className="load-status";note.textContent="Meretuule on fiktiivne esitlus. Broneeringud ei anna õigust päris teenusele.";hotelElement("faq-list").append(note);}
}
async function loadHotel(){
  await Promise.allSettled([
    publicData("/api/public/property").then(renderRestaurantProperty).catch(()=>{hotelElement("phone-number").hidden=true;hotelElement("phone-number").removeAttribute("href");hotelElement("phone-number").textContent="";hotelElement("phone-status").textContent="Demonumbri andmeid ei saanud kontrollida. Kasuta veebis Kõneproovi.";hotelElement("opening-hours").replaceChildren();hotelElement("hours-status").textContent="Lahtiolekuaegu ei saanud praegu laadida.";hotelElement("faq-list").textContent="Demokeskkonna teavet ei saanud laadida. Meretuule on fiktiivne esitlus.";}),
    publicData("/api/public/catalogue").then(data=>{
      const catalogue=Array.isArray(data.tables)?data:data.tables;
      if(!catalogue || !Array.isArray(catalogue.tables) || !catalogue.rules)throw new Error("restaurant_catalogue_unavailable");
      renderRestaurantTables(catalogue.tables);renderRestaurantRules(catalogue.rules);
      if(Array.isArray(data.menu || catalogue.menu))renderRestaurantMenu(data.menu || catalogue.menu);
      else if(!hotelElement("menu-list").children.length)hotelStatus("menu-status","Demomenüü andmed pole praegu saadaval.",true);
    }).catch(()=>{hotelElement("table-grid").replaceChildren();hotelStatus("tables-status","Laudade kataloogi ei saanud laadida. Saadavus pole kinnitatud.",true);hotelStatus("menu-status","Demomenüü lugemine ebaõnnestus; kuvatud menüü võib olla aegunud.",true);hotelStatus("rules-status","Kataloogi reegleid ei saanud kontrollida; kuvatud teave võib olla aegunud.",true);})
  ]);
}
loadHotel();
