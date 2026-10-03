"use strict";

const demoFaq = [
  ["Kas Meretuule Köök on päris restoran?", "Ei. See on restoranidele mõeldud väljamõeldud tooteesitlus."],
  ["Kas saan siin päris lauda broneerida?", "Ei. Kõneproov näitab demo töövoogu ega saada päris restorani broneeringut."],
  ["Kas menüü ja hinnad on päriselt saadaval?", "Ei. Menüü on näidis. Päris restoran lisab enda kinnitatud road, hinnad ja allergeeniteabe."],
  ["Kuidas häälabilist proovida?", "Ava restorani töölaud ja alusta kõneproovi. Mikrofon küsib kasutamisel eraldi luba."]
];

function renderFaq() {
  const list = document.getElementById("faq-list");
  list.replaceChildren();
  for (const [question, copy] of demoFaq) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const answer = document.createElement("p");
    summary.textContent = question;
    answer.textContent = copy;
    details.append(summary, answer);
    list.append(details);
  }
}

renderFaq();
document.getElementById("hours-status").textContent = "Restorani lahtiolekuaegu pole demo jaoks kinnitatud.";
document.getElementById("phone-status").textContent = "Päris restoraninumbrit pole seadistatud. Proovi virtuaalset abilist operaatori töölaual.";
