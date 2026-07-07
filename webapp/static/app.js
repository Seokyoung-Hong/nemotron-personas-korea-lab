const state = {
  segments: [],
  selectedSegment: null,
  hypotheses: [],
};

const fmt = new Intl.NumberFormat('ko-KR');
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function addMessage(role, title, html) {
  const stream = $('chatStream');
  const node = document.createElement('div');
  node.className = `message ${role}`;
  node.innerHTML = `
    <div class="avatar">${role === 'user' ? 'YOU' : 'AI'}</div>
    <div class="bubble">
      <div class="message-title">${title}</div>
      ${html}
    </div>
  `;
  stream.appendChild(node);
  stream.scrollTop = stream.scrollHeight;
}

function renderMetrics(summary) {
  $('sidebarMeta').textContent = `${fmt.format(summary.row_count)} personas · ${fmt.format(summary.persona_candidate_count)} candidate personas`;
  const metrics = [
    ['전체 페르소나', summary.row_count],
    ['UUID 유니크', summary.distinct_uuid_count],
    ['Persona 후보', summary.persona_candidate_count],
    ['검증 질문', summary.question_count],
  ];
  $('metricGrid').innerHTML = metrics.map(([label, value]) => `
    <div class="metric-card">
      <div class="metric-value">${fmt.format(value)}</div>
      <div class="metric-label">${label}</div>
    </div>
  `).join('');
}

function renderSegments() {
  const nav = $('segmentNav');
  nav.innerHTML = '<div class="nav-caption">세그먼트</div>' + state.segments.map((segment) => `
    <button class="segment-button ${state.selectedSegment?.id === segment.id ? 'active' : ''}" data-segment-id="${segment.id}">
      <strong>${segment.segment_name}</strong>
      <span>${fmt.format(segment.sample_size)} candidates</span>
    </button>
  `).join('');
  nav.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => selectSegment(button.dataset.segmentId));
  });
}

function renderHypotheses(data) {
  state.hypotheses = data.hypotheses || [];
  $('hypothesisList').innerHTML = state.hypotheses.map((item) => `
    <div class="hypothesis-card">
      <strong>${item.hypothesis}</strong>
      <div class="tiny-label">${item.hypothesis_type} · confidence ${item.confidence_before_validation}</div>
      <ul>${item.questions.map((q) => `<li>${q.question}</li>`).join('')}</ul>
    </div>
  `).join('') || '<p>가설이 없습니다.</p>';
  $('hypothesisSelect').innerHTML = state.hypotheses.map((item) => `
    <option value="${item.hypothesis_id}">${item.hypothesis_id}</option>
  `).join('');
}

function personaCard(row) {
  return `
    <div class="persona-card">
      <div class="persona-meta">${row.age}세 · ${row.sex} · ${row.province} ${row.district} · ${row.occupation}</div>
      <div>${row.persona || ''}</div>
      <div style="margin-top:8px;color:#9ba7b8">${row.culinary_persona || ''}</div>
    </div>
  `;
}

async function selectSegment(segmentId) {
  state.selectedSegment = state.segments.find((segment) => segment.id === segmentId);
  renderSegments();
  $('selectedTitle').textContent = state.selectedSegment.segment_name;
  $('selectedRationale').textContent = state.selectedSegment.rationale;
  $('selectedCount').textContent = `${fmt.format(state.selectedSegment.sample_size)} candidates`;

  const [hypotheses, personas] = await Promise.all([
    api(`/api/hypotheses?segment_id=${encodeURIComponent(segmentId)}`),
    api(`/api/personas?segment_id=${encodeURIComponent(segmentId)}&limit=3`),
  ]);
  renderHypotheses(hypotheses);
  addMessage('assistant', state.selectedSegment.segment_name, `
    <p>${state.selectedSegment.rationale}</p>
    ${personas.personas.map(personaCard).join('')}
  `);
}

async function searchPersonas(event) {
  event.preventDefault();
  const q = $('queryInput').value.trim();
  const province = $('provinceInput').value;
  const params = new URLSearchParams({ limit: '5' });
  if (q) params.set('q', q);
  if (province) params.set('province', province);
  if (state.selectedSegment) params.set('segment_id', state.selectedSegment.id);
  addMessage('user', '검색', `<p>${q || '전체'} / ${province || '전국'}</p>`);
  const data = await api(`/api/personas?${params.toString()}`);
  addMessage('assistant', '페르소나 검색 결과', data.personas.map(personaCard).join('') || '<p>조건에 맞는 결과가 없습니다.</p>');
}

async function submitValidation(event) {
  event.preventDefault();
  const payload = {
    hypothesis_id: $('hypothesisSelect').value,
    method: 'field_interview',
    respondent_profile: $('respondentInput').value.trim(),
    result_summary: $('resultInput').value.trim(),
    evidence_level: $('evidenceInput').value,
    validated: $('validatedInput').checked,
  };
  const result = await api('/api/validation-results', { method: 'POST', body: JSON.stringify(payload) });
  $('validationStatus').textContent = `저장 완료: ${result.id}`;
  $('resultInput').value = '';
  addMessage('assistant', '검증 결과 저장', `<p>${payload.respondent_profile}: ${payload.result_summary}</p>`);
}

async function createWorkspace() {
  const workspaceName = window.prompt('새 가설 워크스페이스 이름을 입력하세요.');
  if (!workspaceName?.trim()) return;
  const hypothesis = window.prompt('검증할 핵심 가설을 입력하세요.');
  if (!hypothesis?.trim()) return;
  const question = window.prompt('첫 번째 검증 질문을 입력하세요. (선택)', '오늘 메뉴를 언제, 어디서 확인하나요?') || '';
  const query = window.prompt('페르소나 필터 키워드를 입력하세요. (선택)', $('queryInput').value.trim() || '점심') || '';
  const province = window.prompt('지역 필터를 입력하세요. 예: 경기, 서울 (선택)', $('provinceInput').value || '') || '';

  addMessage('user', '새 가설 워크스페이스', `<p>${workspaceName}</p><p>${hypothesis}</p>`);
  const created = await api('/api/workspaces', {
    method: 'POST',
    body: JSON.stringify({
      workspace_name: workspaceName.trim(),
      hypothesis: hypothesis.trim(),
      question: question.trim(),
      query: query.trim(),
      province: province.trim(),
      rationale: 'User-created hypothesis workspace.',
    }),
  });
  const segments = await api('/api/segments');
  state.segments = segments.segments;
  renderSegments();
  $('validationStatus').textContent = `워크스페이스 저장 완료: ${created.segment.id}`;
  await selectSegment(created.segment.id);
}

async function boot() {
  const [summary, segments] = await Promise.all([api('/api/summary'), api('/api/segments')]);
  renderMetrics(summary);
  state.segments = segments.segments;
  renderSegments();
  if (state.segments[0]) await selectSegment(state.segments[0].id);
}

$('searchForm').addEventListener('submit', searchPersonas);
$('validationForm').addEventListener('submit', submitValidation);
$('refreshBtn').addEventListener('click', boot);
$('newWorkspaceBtn').addEventListener('click', () => {
  createWorkspace().catch((err) => {
    console.error(err);
    addMessage('assistant', '워크스페이스 생성 오류', `<p>${err.message}</p>`);
  });
});

boot().catch((err) => {
  console.error(err);
  addMessage('assistant', '오류', `<p>${err.message}</p>`);
});
