/* ============================================
   SoundHaven — Store Logic
   ============================================ */

// ---- Star SVG generation ----

function starSVG(filled) {
  if (filled) {
    return `<svg class="star" viewBox="0 0 20 20" fill="currentColor"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.162c.969 0 1.371 1.24.588 1.81l-3.37 2.448a1 1 0 00-.364 1.118l1.287 3.957c.3.921-.755 1.688-1.54 1.118l-3.37-2.448a1 1 0 00-1.176 0l-3.37 2.448c-.784.57-1.838-.197-1.539-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.063 9.384c-.783-.57-.38-1.81.588-1.81h4.162a1 1 0 00.95-.69l1.286-3.957z"/></svg>`;
  }
  return `<svg class="star empty" viewBox="0 0 20 20" fill="currentColor"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.286 3.957a1 1 0 00.95.69h4.162c.969 0 1.371 1.24.588 1.81l-3.37 2.448a1 1 0 00-.364 1.118l1.287 3.957c.3.921-.755 1.688-1.54 1.118l-3.37-2.448a1 1 0 00-1.176 0l-3.37 2.448c-.784.57-1.838-.197-1.539-1.118l1.287-3.957a1 1 0 00-.364-1.118L2.063 9.384c-.783-.57-.38-1.81.588-1.81h4.162a1 1 0 00.95-.69l1.286-3.957z"/></svg>`;
}

function renderStars(rating) {
  let html = '<div class="stars">';
  for (let i = 1; i <= 5; i++) {
    html += starSVG(i <= Math.round(rating));
  }
  html += '</div>';
  return html;
}

// ---- Data loading ----

async function loadProducts() {
  const res = await fetch('/data/products-small.json');
  return res.json();
}

async function loadProduct(id) {
  const products = await loadProducts();
  return products.find(p => p.id === parseInt(id));
}

// ---- Cart (localStorage) ----

function getCart() {
  try {
    return JSON.parse(localStorage.getItem('soundhaven_cart') || '[]');
  } catch {
    return [];
  }
}

function saveCart(cart) {
  localStorage.setItem('soundhaven_cart', JSON.stringify(cart));
  updateCartCount();
}

function addToCart(product) {
  const cart = getCart();
  const existing = cart.find(item => item.id === product.id);
  if (existing) {
    existing.qty += 1;
  } else {
    cart.push({
      id: product.id,
      name: product.name,
      brand: product.brand,
      price: product.price,
      image: product.image,
      qty: 1
    });
  }
  saveCart(cart);
}

function removeFromCart(productId) {
  let cart = getCart();
  cart = cart.filter(item => item.id !== productId);
  saveCart(cart);
}

function updateQty(productId, delta) {
  const cart = getCart();
  const item = cart.find(i => i.id === productId);
  if (item) {
    item.qty = Math.max(1, item.qty + delta);
    saveCart(cart);
  }
}

function getCartTotal() {
  return getCart().reduce((sum, item) => sum + item.price * item.qty, 0);
}

function getCartCount() {
  return getCart().reduce((sum, item) => sum + item.qty, 0);
}

function updateCartCount() {
  const el = document.querySelector('.cart-count');
  if (el) {
    const count = getCartCount();
    el.textContent = count;
    el.setAttribute('data-count', count);
  }
}

// ---- Toast notification ----

function showToast(message) {
  let toast = document.querySelector('.toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2500);
}

// ---- Product Listing Page ----

async function renderProductGrid() {
  const container = document.getElementById('product-grid');
  if (!container) return;

  const products = await loadProducts();

  container.innerHTML = products.map(p => `
    <div class="product-card">
      <a href="/product.html?id=${p.id}">
        <div class="product-card-image">
          ${p.badge ? `<span class="product-badge" style="background:${p.badgeColor}">${p.badge}</span>` : ''}
          <img src="${p.image}" alt="${p.name}">
        </div>
        <div class="product-card-body">
          <div class="product-card-brand">${p.brand}</div>
          <div class="product-card-name">${p.name}</div>
          <div class="product-card-desc">${p.shortDescription}</div>
          <div class="product-card-footer">
            <div class="product-price">${p.price.toFixed(2)}</div>
            <div class="star-rating">
              ${renderStars(p.rating)}
              <span class="rating-text">${p.rating}</span>
              <span class="review-count">(${p.reviewCount.toLocaleString()})</span>
            </div>
          </div>
        </div>
      </a>
    </div>
  `).join('');
}

// ---- Product Detail Page ----

async function renderProductDetail() {
  const container = document.getElementById('product-detail');
  if (!container) return;

  const params = new URLSearchParams(window.location.search);
  const id = params.get('id');
  if (!id) return;

  const product = await loadProduct(id);
  if (!product) {
    container.innerHTML = '<p>Product not found.</p>';
    return;
  }

  document.title = `${product.name} — SoundHaven`;

  // Breadcrumb
  const breadcrumb = document.getElementById('breadcrumb-name');
  if (breadcrumb) breadcrumb.textContent = product.name;

  // Main detail
  container.innerHTML = `
    <div class="product-gallery">
      ${product.badge ? `<span class="product-badge" style="background:${product.badgeColor}">${product.badge}</span>` : ''}
      <img src="${product.image}" alt="${product.name}">
    </div>
    <div class="product-info">
      <div class="product-brand">${product.brand}</div>
      <h1>${product.name}</h1>
      <div class="price-row">
        <div class="product-price">${product.price.toFixed(2)}</div>
      </div>
      <div class="product-rating-detail">
        ${renderStars(product.rating)}
        <span class="rating-text">${product.rating}</span>
        <span class="review-count">${product.reviewCount.toLocaleString()} reviews</span>
      </div>
      <div class="product-description">${product.description}</div>
      <button class="add-to-cart-btn" id="add-to-cart-btn">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>
        Add to Cart
      </button>
    </div>
  `;

  // Specs table
  const specsContainer = document.getElementById('specs-table');
  if (specsContainer && product.specs) {
    specsContainer.innerHTML = Object.entries(product.specs).map(([key, val]) =>
      `<tr><td>${key}</td><td>${val}</td></tr>`
    ).join('');
  }

  // Reviews
  const reviewsContainer = document.getElementById('reviews-list');
  if (reviewsContainer && product.reviews) {
    reviewsContainer.innerHTML = product.reviews.map(r => `
      <div class="review-card">
        <div class="review-header">
          <span class="review-author">${r.author}</span>
          <span class="review-date">${new Date(r.date).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}</span>
        </div>
        <div class="review-stars">${renderStars(r.rating)}</div>
        <div class="review-text">${r.text}</div>
      </div>
    `).join('');
  }

  // Add to cart button
  const btn = document.getElementById('add-to-cart-btn');
  if (btn) {
    btn.addEventListener('click', () => {
      addToCart(product);
      btn.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> Added to Cart`;
      btn.classList.add('added');
      showToast(`${product.name} added to cart`);
      setTimeout(() => {
        btn.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg> Add to Cart`;
        btn.classList.remove('added');
      }, 2000);
    });
  }
}

// ---- Cart Page ----

async function renderCart() {
  const container = document.getElementById('cart-items');
  const summaryContainer = document.getElementById('cart-summary');
  if (!container) return;

  const cart = getCart();

  if (cart.length === 0) {
    container.innerHTML = `
      <div class="cart-empty">
        <div class="cart-empty-icon">🛒</div>
        <h2>Your cart is empty</h2>
        <p>Looks like you haven't added any products yet.</p>
        <a href="/products.html" class="add-to-cart-btn" style="display:inline-flex; max-width:220px;">Browse Products</a>
      </div>
    `;
    if (summaryContainer) summaryContainer.style.display = 'none';
    return;
  }

  container.innerHTML = cart.map(item => `
    <div class="cart-item" data-id="${item.id}">
      <div class="cart-item-image">
        <img src="${item.image}" alt="${item.name}">
      </div>
      <div class="cart-item-info">
        <div class="cart-item-name">${item.name}</div>
        <div class="cart-item-brand">${item.brand}</div>
      </div>
      <div class="cart-item-qty">
        <button class="qty-btn" onclick="handleQty(${item.id}, -1)">−</button>
        <span>${item.qty}</span>
        <button class="qty-btn" onclick="handleQty(${item.id}, 1)">+</button>
      </div>
      <div class="cart-item-price">$${(item.price * item.qty).toFixed(2)}</div>
      <button class="cart-item-remove" onclick="handleRemove(${item.id})">✕</button>
    </div>
  `).join('');

  if (summaryContainer) {
    const subtotal = getCartTotal();
    const shipping = subtotal > 50 ? 0 : 5.99;
    const total = subtotal + shipping;

    summaryContainer.innerHTML = `
      <div class="cart-summary-row">
        <span>Subtotal</span>
        <span>$${subtotal.toFixed(2)}</span>
      </div>
      <div class="cart-summary-row">
        <span>Shipping</span>
        <span>${shipping === 0 ? 'Free' : '$' + shipping.toFixed(2)}</span>
      </div>
      <div class="cart-summary-total">
        <span>Total</span>
        <span>$${total.toFixed(2)}</span>
      </div>
      <a href="/checkout.html"><button class="checkout-btn">Proceed to Checkout</button></a>
      <a href="/products.html" class="continue-shopping">← Continue Shopping</a>
    `;
    summaryContainer.style.display = 'block';
  }
}

function handleQty(productId, delta) {
  updateQty(productId, delta);
  renderCart();
}

function handleRemove(productId) {
  removeFromCart(productId);
  renderCart();
}

// ---- Checkout Page ----

async function renderCheckoutSummary() {
  const container = document.getElementById('checkout-order-summary');
  if (!container) return;

  const cart = getCart();
  if (cart.length === 0) {
    window.location.href = '/cart.html';
    return;
  }

  const subtotal = getCartTotal();
  const shipping = subtotal > 50 ? 0 : 5.99;
  const total = subtotal + shipping;

  container.innerHTML = `
    ${cart.map(item => `
      <div class="cart-summary-row">
        <span>${item.name} × ${item.qty}</span>
        <span>$${(item.price * item.qty).toFixed(2)}</span>
      </div>
    `).join('')}
    <div class="cart-summary-row" style="padding-top:12px; border-top:1px solid var(--color-border); margin-top:12px;">
      <span>Shipping</span>
      <span>${shipping === 0 ? 'Free' : '$' + shipping.toFixed(2)}</span>
    </div>
    <div class="cart-summary-total">
      <span>Total</span>
      <span>$${total.toFixed(2)}</span>
    </div>
  `;
}

// ---- Init ----

document.addEventListener('DOMContentLoaded', () => {
  updateCartCount();
  renderProductGrid();
  renderProductDetail();
  renderCart();
  renderCheckoutSummary();
});
