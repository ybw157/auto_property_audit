import { createRouter, createWebHistory } from 'vue-router'
import NProgress from 'nprogress'
import 'nprogress/nprogress.css'
import { useAuthStore } from '../stores/auth'

NProgress.configure({ showSpinner: false })

const routes = [
  { path: '/login', component: () => import('../pages/Login.vue'), meta: { title: '登录', public: true } },
  {
    path: '/',
    component: () => import('../layouts/Layout.vue'),
    children: [
      { path: 'dashboard', component: () => import('../pages/Dashboard.vue'), meta: { title: '首页', roles: ['group_admin'] } },
      // AI审核已并入审核结果页顶部，/audit 重定向过去
      { path: 'audit', redirect: '/results' },
      { path: 'results', component: () => import('../pages/AuditResults.vue'), meta: { title: '审核结果', roles: ['project_user'] } },
      { path: 'confirmation', component: () => import('../pages/ConfirmationPage.vue'), meta: { title: '异常确认', roles: ['project_user'] } },
      { path: 'reports', component: () => import('../pages/PdfReports.vue'), meta: { title: 'PDF报告', roles: ['project_user'] } },
      { path: 'contracts', component: () => import('../pages/ContractManagement.vue'), meta: { title: '合同管理', roles: ['group_admin', 'project_user'] } },
      { path: 'project-management', component: () => import('../pages/ProjectManagement.vue'), meta: { title: '项目管理', roles: ['group_admin'] } },
      { path: 'bi-upload', component: () => import('../pages/BiUpload.vue'), meta: { title: 'BI考勤', roles: ['group_admin'] } },
      { path: 'bi-sync', component: () => import('../pages/BiSync.vue'), meta: { title: 'BI同步', roles: ['group_admin'] } },
      { path: 'user-management', component: () => import('../pages/UserManagement.vue'), meta: { title: '用户管理', roles: ['group_admin'] } },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory('/audit/'),
  routes,
})

/** 角色落地页 */
export function homePathOf(role: string) {
  return role === 'group_admin' ? '/dashboard' : '/results'
}

router.beforeEach(async (to) => {
  NProgress.start()
  // 页面标题随路由更新（取自 vue-admin-template 的模式）
  const baseTitle = '物业集团保安保洁智能审核平台'
  document.title = to.meta.title ? `${to.meta.title} - ${baseTitle}` : baseTitle

  const auth = useAuthStore()
  if (auth.loading) {
    await auth.restore()
  }
  if (to.meta.public) {
    return true
  }
  if (!auth.user) {
    return { path: '/login', replace: true }
  }
  // 根路径与未知路径按角色落各自首页
  if (to.path === '/') {
    return { path: homePathOf(auth.role), replace: true }
  }
  // 页面级角色拦截
  const allowed = to.meta.roles as string[] | undefined
  if (allowed && !allowed.includes(auth.role)) {
    return { path: homePathOf(auth.role), replace: true }
  }
  return true
})

router.afterEach(() => {
  NProgress.done()
})
