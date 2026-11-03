<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <div class="budget-top">
        <label class="budget-label" for="budget-slider">{{ t('restocking.budget') }}</label>
        <div class="budget-value">{{ money(budget) }}</div>
      </div>
      <input
        id="budget-slider"
        v-model.number="budget"
        class="budget-slider"
        type="range"
        :min="BUDGET_MIN"
        :max="BUDGET_MAX"
        :step="BUDGET_STEP"
        :aria-label="t('restocking.budget')"
        :aria-valuetext="money(budget)"
      />
      <div class="budget-range">
        <span>{{ money(BUDGET_MIN) }}</span>
        <span>{{ money(BUDGET_MAX) }}</span>
      </div>
      <p class="budget-hint">{{ t('restocking.budgetHint') }}</p>
    </div>

    <div v-if="loading && !result" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="result" :class="{ refreshing: loading }">
      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ money(result.total_cost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ money(result.remaining_budget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.longestLeadTime') }}</div>
          <div class="stat-value">{{ t('restocking.leadTimeDays', { days: result.lead_time_days }) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ items.length }})</h3>
          <button
            type="button"
            class="btn-primary"
            :disabled="!canPlaceOrder"
            @click="openConfirm"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="items.length === 0" class="empty-state">{{ t('restocking.empty') }}</div>
        <div v-else class="table-container">
          <table class="restocking-table">
            <thead>
              <tr>
                <th>{{ t('restocking.sku') }}</th>
                <th>{{ t('restocking.item') }}</th>
                <th>{{ t('restocking.trend') }}</th>
                <th class="num">{{ t('restocking.demandGap') }}</th>
                <th class="num">{{ t('restocking.quantity') }}</th>
                <th class="num">{{ t('restocking.unitCost') }}</th>
                <th class="num">{{ t('restocking.lineTotal') }}</th>
                <th class="num">{{ t('restocking.leadTime') }}</th>
                <th>{{ t('restocking.supplier') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.item_sku">
                <td><strong>{{ item.item_sku }}</strong></td>
                <td>{{ translateProductName(item.item_name) }}</td>
                <td>
                  <span :class="['badge', trendClass(item.trend)]">{{ trendLabel(item.trend) }}</span>
                </td>
                <td class="num">{{ item.demand_gap.toLocaleString() }}</td>
                <td class="num">{{ item.quantity.toLocaleString() }}</td>
                <td class="num">{{ unitMoney(item.unit_cost) }}</td>
                <td class="num"><strong>{{ money(item.line_total) }}</strong></td>
                <td class="num">{{ t('restocking.leadTimeDays', { days: item.lead_time_days }) }}</td>
                <td>{{ item.supplier_name }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="showConfirm" class="modal-overlay" @click="closeConfirm">
        <div
          class="modal-container"
          role="dialog"
          aria-modal="true"
          aria-labelledby="restock-confirm-title"
          @click.stop
        >
          <div class="modal-header">
            <h3 id="restock-confirm-title" class="modal-title">{{ t('restocking.confirmTitle') }}</h3>
            <button type="button" class="close-button" :aria-label="t('restocking.cancel')" @click="closeConfirm">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M15 5L5 15M5 5L15 15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <p class="confirm-message">{{ t('restocking.confirmMessage', { count: items.length }) }}</p>
            <ul class="confirm-list">
              <li v-for="item in items" :key="item.item_sku" class="confirm-row">
                <span class="confirm-sku">{{ item.item_sku }}</span>
                <span class="confirm-qty">&times; {{ item.quantity.toLocaleString() }}</span>
                <span class="confirm-total">{{ money(item.line_total) }}</span>
              </li>
            </ul>
            <div class="confirm-summary">
              <div>
                <span>{{ t('restocking.totalCost') }}</span>
                <strong>{{ money(result ? result.total_cost : 0) }}</strong>
              </div>
              <div>
                <span>{{ t('restocking.leadTime') }}</span>
                <strong>{{ t('restocking.leadTimeDays', { days: result ? result.lead_time_days : 0 }) }}</strong>
              </div>
            </div>
            <div v-if="orderError" class="modal-error" role="alert">{{ orderError }}</div>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn-secondary" :disabled="submitting" @click="closeConfirm">
              {{ t('restocking.cancel') }}
            </button>
            <button type="button" class="btn-primary" :disabled="submitting" @click="confirmOrder">
              {{ submitting ? t('restocking.placing') : t('restocking.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

const BUDGET_MIN = 0
const BUDGET_MAX = 100000
const BUDGET_STEP = 500
const DEBOUNCE_MS = 300

const router = useRouter()
const { t, te, currentCurrency, translateProductName } = useI18n()

const budget = ref(25000) // always USD; conversion happens only for display
const result = ref(null)
const loading = ref(true)
const error = ref(null)
const submitting = ref(false)
const showConfirm = ref(false)
const orderError = ref(null)

let debounceTimer = null
let requestCounter = 0

const items = computed(() => (result.value ? result.value.items : []))
const canPlaceOrder = computed(() => items.value.length > 0 && !loading.value && !submitting.value)

const money = (usd) => formatCurrency(usd, currentCurrency.value)
// Unit costs have cents (e.g. $42.50); whole-dollar rounding would misstate the price
const unitMoney = (usd) => formatCurrencyWithDecimals(usd, currentCurrency.value, 2)

const trendClass = (trend) => {
  if (trend === 'increasing') return 'success'
  if (trend === 'decreasing') return 'warning'
  return 'info'
}

const trendLabel = (trend) => {
  const key = `trends.${trend}`
  if (typeof te === 'function' && te(key)) return t(key)
  const label = t(key)
  if (label && label !== key) return label
  return trend ? trend.charAt(0).toUpperCase() + trend.slice(1) : ''
}

const loadRecommendations = async () => {
  // Each request gets an id; only the latest one may update state
  const requestId = ++requestCounter
  loading.value = true
  error.value = null
  try {
    const data = await api.getRestockRecommendations(budget.value)
    if (requestId !== requestCounter) return
    result.value = data
  } catch (err) {
    if (requestId !== requestCounter) return
    error.value = t('restocking.error')
    console.error('Failed to load restock recommendations:', err)
  } finally {
    if (requestId === requestCounter) loading.value = false
  }
}

watch(budget, () => {
  clearTimeout(debounceTimer)
  // Mark as loading immediately so Place Order cannot use stale items
  loading.value = true
  debounceTimer = setTimeout(loadRecommendations, DEBOUNCE_MS)
})

const openConfirm = () => {
  if (!canPlaceOrder.value) return
  orderError.value = null
  showConfirm.value = true
}

const closeConfirm = () => {
  if (submitting.value) return
  showConfirm.value = false
}

const confirmOrder = async () => {
  if (submitting.value || !canPlaceOrder.value) return // prevent double submission
  submitting.value = true
  orderError.value = null
  try {
    await api.createRestockOrder({
      budget: budget.value,
      items: items.value.map(i => ({ item_sku: i.item_sku, quantity: i.quantity }))
    })
    showConfirm.value = false
    submitting.value = false
    router.push('/orders')
  } catch (err) {
    orderError.value = (err.response && err.response.data && err.response.data.detail) || t('restocking.orderError')
    console.error('Failed to place restock order:', err)
  } finally {
    submitting.value = false
  }
}

const onKeydown = (e) => {
  if (e.key === 'Escape' && showConfirm.value) closeConfirm()
}

onMounted(() => {
  loadRecommendations()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  clearTimeout(debounceTimer)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.budget-card {
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.budget-label {
  font-size: 0.813rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
}

.budget-value {
  font-size: 2rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 8px;
  background: transparent;
  cursor: pointer;
}

.budget-slider::-webkit-slider-runnable-track {
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
}

.budget-slider::-moz-range-track {
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 22px;
  height: 22px;
  margin-top: -7px;
  border-radius: 50%;
  background: #0f172a;
  border: 3px solid #fff;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.35);
}

.budget-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #0f172a;
  border: 3px solid #fff;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.35);
}

.budget-slider:focus-visible {
  outline: 2px solid #64748b;
  outline-offset: 4px;
  border-radius: 4px;
}

.budget-range {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.813rem;
  color: #64748b;
}

.budget-hint {
  margin: 0.75rem 0 0;
  font-size: 0.875rem;
  color: #64748b;
}

.refreshing {
  opacity: 0.6;
  transition: opacity 0.15s ease;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.restocking-table th.num,
.restocking-table td.num {
  text-align: right;
  white-space: nowrap;
}

.btn-primary,
.btn-secondary {
  padding: 0.625rem 1.25rem;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.btn-primary {
  background: #0f172a;
  border: 1px solid #0f172a;
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  background: #1e293b;
}

.btn-secondary {
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #334155;
}

.btn-secondary:hover:not(:disabled) {
  background: #e2e8f0;
  border-color: #cbd5e1;
}

.btn-primary:disabled,
.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Modal (pattern copied from ProductDetailModal.vue) */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 1rem;
}

.modal-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15);
  max-width: 560px;
  width: 100%;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.5rem;
  border-bottom: 1px solid #e2e8f0;
}

.modal-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.025em;
}

.close-button {
  background: none;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.close-button:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
}

.confirm-message {
  margin: 0 0 1rem;
  color: #334155;
}

.confirm-list {
  list-style: none;
  margin: 0 0 1rem;
  padding: 0;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.confirm-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 1rem;
  padding: 0.625rem 0.875rem;
  font-size: 0.875rem;
  color: #0f172a;
}

.confirm-row + .confirm-row {
  border-top: 1px solid #e2e8f0;
}

.confirm-sku {
  font-weight: 600;
}

.confirm-qty {
  color: #64748b;
}

.confirm-total {
  min-width: 5rem;
  text-align: right;
}

.confirm-summary {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  font-size: 0.938rem;
  color: #64748b;
}

.confirm-summary > div {
  display: flex;
  justify-content: space-between;
}

.confirm-summary strong {
  color: #0f172a;
}

.modal-error {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  font-size: 0.875rem;
}

.modal-footer {
  padding: 1.5rem;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}
</style>
