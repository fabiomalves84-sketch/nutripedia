const $ = (selector) => document.querySelector(selector);
const form = $('#resource-form');
const dialog = $('#editor');
let favoritesOnly = false;
let activeRequest;

const ageTabs = [...document.querySelectorAll('[role="tab"][data-age]')];
function selectAge(tab) {
  for (const candidate of ageTabs) {
    const selected = candidate === tab;
    candidate.setAttribute('aria-selected', selected);
    candidate.tabIndex = selected ? 0 : -1;
    document.getElementById(candidate.getAttribute('aria-controls')).hidden = !selected;
  }
}
for (const [index, tab] of ageTabs.entries()) {
  tab.addEventListener('click', () => selectAge(tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === 'ArrowRight' ? 1 : -1;
    const next = ageTabs[(index + direction + ageTabs.length) % ageTabs.length];
    selectAge(next);
    next.focus();
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': $('meta[name="csrf-token"]').content },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || 'Não foi possível concluir. Atualiza a página ou tenta novamente.');
  }
  return response.json();
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function openEditor(resource = {}) {
  form.reset();
  for (const name of ['id', 'title', 'description', 'url']) form.elements[name].value = resource[name] || '';
  if (resource.specialty) form.elements.specialty.value = resource.specialty;
  $('#form-title').textContent = resource.id ? 'Editar referência' : 'Adicionar referência';
  $('#form-error').textContent = '';
  dialog.showModal();
}

function resourceCard(resource) {
  const card = element('article', '', 'card');
  const top = element('div', '', 'card-top');
  top.append(element('span', resource.specialty, 'tag'));
  const favorite = element('button', resource.favorite ? '★' : '☆', 'star');
  favorite.setAttribute('aria-label', `${resource.favorite ? 'Remover dos' : 'Guardar nos'} favoritos: ${resource.title}`);
  favorite.setAttribute('aria-pressed', Boolean(resource.favorite));
  favorite.onclick = async () => {
    favorite.disabled = true;
    try {
      await api(`/api/resources/${resource.id}/favorite`, { method: 'PATCH', body: JSON.stringify({ favorite: !resource.favorite }) });
      await loadResources();
    } catch (error) { $('#status').textContent = error.message; }
    finally { favorite.disabled = false; }
  };
  top.append(favorite);
  card.append(top, element('h3', resource.title), element('p', resource.description, 'description'));
  const bottom = element('div', '', 'card-bottom');
  const link = element('a', 'Consultar fonte ↗');
  link.href = resource.url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  const edit = element('button', 'Editar', 'text-button');
  edit.setAttribute('aria-label', `Editar ${resource.title}`);
  edit.onclick = () => openEditor(resource);
  bottom.append(link, edit);
  card.append(bottom);
  return card;
}

async function loadResources() {
  activeRequest?.abort();
  const controller = new AbortController();
  activeRequest = controller;
  $('#status').textContent = 'A carregar recursos…';
  $('#retry').hidden = true;
  $('#resources').setAttribute('aria-busy', 'true');
  try {
    const params = new URLSearchParams({ q: $('#search').value, specialty: $('#specialty').value, favorites: favoritesOnly ? '1' : '0' });
    const resources = await api(`/api/resources?${params}`, { signal: controller.signal });
    $('#resources').replaceChildren(...resources.map(resourceCard));
    $('#count').textContent = `${resources.length} ${resources.length === 1 ? 'referência' : 'referências'}`;
    $('#status').textContent = resources.length ? '' : favoritesOnly ? 'Ainda não há favoritos com estes filtros. Guarda uma referência usando a estrela.' : 'Nenhuma referência encontrada. Experimenta outro termo ou tema.';
  } catch (error) {
    if (error.name !== 'AbortError') {
      $('#resources').replaceChildren();
      $('#count').textContent = '';
      $('#status').textContent = error.message;
      $('#retry').hidden = false;
    }
  } finally {
    if (activeRequest === controller) $('#resources').setAttribute('aria-busy', 'false');
  }
}

$('#add').onclick = () => openEditor();
$('#close').onclick = () => dialog.close();
$('#retry').onclick = loadResources;
$('#search').addEventListener('input', loadResources);
$('#specialty').addEventListener('change', loadResources);
$('#favorites').onclick = () => {
  favoritesOnly = !favoritesOnly;
  $('#favorites').setAttribute('aria-pressed', favoritesOnly);
  loadResources();
};
form.onsubmit = async (event) => {
  event.preventDefault();
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  const data = Object.fromEntries(new FormData(form));
  try {
    await api(data.id ? `/api/resources/${data.id}` : '/api/resources', { method: data.id ? 'PUT' : 'POST', body: JSON.stringify(data) });
    dialog.close();
    $('#search').value = '';
    $('#specialty').value = '';
    favoritesOnly = false;
    $('#favorites').setAttribute('aria-pressed', 'false');
    await loadResources();
  } catch (error) { $('#form-error').textContent = error.message; }
  finally { submit.disabled = false; }
};
loadResources();
