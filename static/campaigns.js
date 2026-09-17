const $ = (selector) => document.querySelector(selector);
const editor = $('#campaign-editor');
const form = $('#campaign-form');

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': $('meta[name="csrf-token"]').content } });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || 'Não foi possível concluir. Tenta novamente.');
  }
  return response.json();
}

function node(tag, text, className) {
  const item = document.createElement(tag);
  item.textContent = text;
  if (className) item.className = className;
  return item;
}

function percent(part, total) { return total ? `${Math.round(part / total * 100)}%` : '—'; }
function statusLabel(status) { return { active: 'Ativa', paused: 'Em pausa', draft: 'Rascunho' }[status]; }

function campaignCard(campaign) {
  const card = node('article', '', 'campaign-card');
  const top = node('div', '', 'campaign-card-top');
  top.append(node('span', statusLabel(campaign.status), `campaign-state ${campaign.status}`), node('span', campaign.channel, 'campaign-channel'));
  card.append(top, node('h3', campaign.name), node('p', `${campaign.sponsor} · ${campaign.audience}`, 'campaign-meta'));
  const metrics = node('div', '', 'campaign-metrics');
  for (const [label, value] of [['Alcance', campaign.reach.toLocaleString('pt-PT')], ['Aberturas', percent(campaign.opens, campaign.reach)], ['Cliques', percent(campaign.clicks, campaign.reach)]]) {
    const metric = node('div'); metric.append(node('span', label), node('strong', value)); metrics.append(metric);
  }
  card.append(metrics);
  const actions = node('div', '', 'campaign-actions');
  const select = document.createElement('select');
  select.setAttribute('aria-label', `Estado da campanha ${campaign.name}`);
  for (const [value, label] of [['draft', 'Rascunho'], ['active', 'Ativa'], ['paused', 'Em pausa']]) {
    const option = document.createElement('option'); option.value = value; option.textContent = label; option.selected = campaign.status === value; select.append(option);
  }
  select.onchange = async () => {
    select.disabled = true;
    try { await api(`/api/campaigns/${campaign.id}/status`, { method: 'PATCH', body: JSON.stringify({ status: select.value }) }); await loadCampaigns(); }
    catch (error) { $('#campaign-status').textContent = error.message; }
    finally { select.disabled = false; }
  };
  actions.append(node('label', 'Alterar estado'), select); card.append(actions);
  return card;
}

async function loadCampaigns() {
  $('#campaign-status').textContent = 'A carregar campanhas…';
  try {
    const campaigns = await api('/api/campaigns');
    $('#campaign-list').replaceChildren(...campaigns.map(campaignCard));
    $('#campaign-count').textContent = `${campaigns.length} campanhas`;
    const totals = campaigns.reduce((sum, campaign) => ({ reach: sum.reach + campaign.reach, opens: sum.opens + campaign.opens, clicks: sum.clicks + campaign.clicks }), { reach: 0, opens: 0, clicks: 0 });
    $('#total-reach').textContent = totals.reach.toLocaleString('pt-PT');
    $('#open-rate').textContent = percent(totals.opens, totals.reach);
    $('#click-rate').textContent = percent(totals.clicks, totals.reach);
    $('#campaign-status').textContent = '';
  } catch (error) { $('#campaign-status').textContent = error.message; }
}

$('#new-campaign').onclick = () => { form.reset(); $('#campaign-error').textContent = ''; editor.showModal(); };
$('#close-campaign').onclick = () => editor.close();
form.onsubmit = async (event) => {
  event.preventDefault();
  const submit = form.querySelector('[type="submit"]'); submit.disabled = true;
  try { await api('/api/campaigns', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form))) }); editor.close(); await loadCampaigns(); }
  catch (error) { $('#campaign-error').textContent = error.message; }
  finally { submit.disabled = false; }
};
loadCampaigns();
