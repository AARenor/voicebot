"use strict";
const hotelElement=id=>document.getElementById(id);
const dayLabels={monday:"Esmaspäev",tuesday:"Teisipäev",wednesday:"Kolmapäev",thursday:"Neljapäev",friday:"Reede",saturday:"Laupäev",sunday:"Pühapäev"};
function hotelStatus(id,message,error=false){const element=hotelElement(id);element.textContent=message;element.className="load-status"+(error?" error":"");}
async function publicData(path){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
  try{const response=await fetch(path,{signal:controller.signal,cache:"no-store",credentials:"omit"});if(!response.ok)throw new Error("public_read_unavailable");return await response.json();}
  finally{clearTimeout(timeout);}
}
function renderHotelRooms(rooms){
  const items=rooms?.room_types || [];
  hotelElement("room-grid").replaceChildren();
  items.forEach((room,index)=>{
    const card=document.createElement("article"),art=document.createElement("div"),windowArt=document.createElement("div"),bed=document.createElement("div"),caption=document.createElement("span"),content=document.createElement("div"),title=document.createElement("h3"),description=document.createElement("p"),amenities=document.createElement("ul"),bottom=document.createElement("div"),capacity=document.createElement("span"),link=document.createElement("a");
    card.className="room-card";art.className="room-art palette-"+(index%3);art.setAttribute("aria-hidden","true");windowArt.className="room-window";bed.className="room-bed";caption.className="room-art-caption";caption.textContent="FIKTIIVSE TOA ILLUSTRATSIOON";art.append(windowArt,bed,caption);
    content.className="room-content";title.textContent=room.name;description.textContent=room.description;amenities.className="room-amenities";
    for(const name of room.amenities || []){const item=document.createElement("li");item.textContent=name;amenities.append(item);}
    bottom.className="room-bottom";capacity.textContent="Kuni "+room.capacity+" külalist";link.className="text-link";link.href="/?"+new URLSearchParams({book:"stay",room:String(room.id)});link.textContent="Kontrolli saadavust ↗";link.setAttribute("aria-label",room.name+": kontrolli demo saadavust");bottom.append(capacity,link);content.append(title,description,amenities,bottom);card.append(art,content);hotelElement("room-grid").append(card);
  });
  hotelStatus("rooms-status",items.length?"Toatüübid sünteetilisest hotellikataloogist. Pildid on illustratsioonid.":"Demotubade kataloog pole praegu saadaval.",!items.length);
}
function renderHotelServices(services){
  hotelElement("service-list").replaceChildren();
  for(const service of services || []){const item=document.createElement("li"),name=document.createElement("span"),duration=document.createElement("span");name.textContent=service.name;duration.textContent=service.duration+" min";item.append(name,duration);hotelElement("service-list").append(item);}
  hotelStatus("spa-status",services?.length?"Teenused demo broneerimissüsteemist. Saadavus kontrollitakse eraldi.":"Spaateenuseid ei saanud praegu laadida.",!services?.length);
}
function renderOpeningHours(property){
  const hours=property.working_hours || property.opening_hours || {};
  hotelElement("opening-hours").replaceChildren();
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
  hotelElement("hours-status").textContent=entries.length?"Ajavöönd: "+(property.timezone || "Europe/Tallinn")+". Vabad ajad kontrollib broneerimissüsteem.":"Lahtiolekuaegade andmed pole praegu saadaval.";
}
function renderHotelProperty(data){
  const property=data.property || {},phone=data.phone || {};
  if(property.description_et)hotelElement("property-description").textContent=property.description_et+" Kõik broneeringud on sünteetilised.";
  const number=phone.number;
  if(phone.configured===true && /^\+[1-9]\d{6,14}$/.test(number || "")){
    hotelElement("phone-number").href="tel:"+number;hotelElement("phone-number").textContent=number;hotelElement("phone-number").hidden=false;
    hotelElement("phone-status").textContent="Seadistatud demonumber. Telefonikõne valmisolekut kontrollib operaator; veebis saad proovida teksti või mikrofoniga.";
  }else{hotelElement("phone-number").hidden=true;hotelElement("phone-status").textContent="Demonumber pole seadistatud. Veebis saad proovida teksti või mikrofoniga.";}
  renderOpeningHours(property);
  hotelElement("faq-list").replaceChildren();
  for(const entry of data.faq || []){const details=document.createElement("details"),summary=document.createElement("summary"),answer=document.createElement("p");summary.textContent=entry.question_et;answer.textContent=entry.answer_et;details.append(summary,answer);hotelElement("faq-list").append(details);}
  if(!data.faq?.length){const note=document.createElement("p");note.className="load-status";note.textContent="Meretuule on fiktiivne esitlus. Broneeringud ei anna õigust päris teenusele.";hotelElement("faq-list").append(note);}
}
async function loadHotel(){
  await Promise.allSettled([
    publicData("/api/public/property").then(renderHotelProperty).catch(()=>{hotelElement("phone-status").textContent="Demonumbri andmeid ei saanud kontrollida. Kasuta veebis Kõneproovi.";hotelElement("hours-status").textContent="Lahtiolekuaegu ei saanud praegu laadida.";hotelElement("faq-list").textContent="Demokeskkonna teavet ei saanud laadida. Meretuule on fiktiivne esitlus.";}),
    publicData("/api/public/catalogue").then(data=>{renderHotelRooms(data.rooms);renderHotelServices(data.services);}).catch(()=>{hotelStatus("rooms-status","Demotubade kataloogi ei saanud laadida. Proovi hiljem uuesti.",true);hotelStatus("spa-status","Spaateenuseid ei saanud laadida. Proovi hiljem uuesti.",true);})
  ]);
}
loadHotel();
