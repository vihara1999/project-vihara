// Modal (index page)
function openModalFrom(card) {
  const d = card.dataset;
  document.getElementById('modalImg').src = d.photo;
  document.getElementById('modalTitle').textContent = d.title;
  document.getElementById('modalMeta').textContent = d.meta;
  document.getElementById('modalCaption').textContent = d.comment ? '「 ' + d.comment + ' 」' : '';
  document.getElementById('modalLink').href = d.link;
  document.getElementById('photoModal').style.display = 'flex';
}
function closeModal() { document.getElementById('photoModal').style.display = 'none'; }
document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.getElementById('photoModal')) closeModal(); });

// Year dropdown on the index page -> reload with ?year=
const ys = document.getElementById('review-year-select');
if (ys) ys.addEventListener('change', () => { location.href = '/?year=' + ys.value + '#reviews'; });

// Photo preview on upload forms
const fi = document.getElementById('photoInput');
if (fi) fi.addEventListener('change', () => {
  const pv = document.getElementById('preview');
  if (fi.files && fi.files[0]) { pv.src = URL.createObjectURL(fi.files[0]); pv.style.display = 'block'; }
});