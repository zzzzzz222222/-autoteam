import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'workspace', component: () => import('@/views/WorkspaceView.vue') },
    {
      path: '/tasks/:taskId',
      name: 'execution',
      component: () => import('@/views/ExecutionView.vue'),
      props: true,
      children: [
        {
          path: 'team',
          name: 'team',
          component: () => import('@/views/TeamView.vue'),
          props: true,
        },
        {
          path: 'artifacts',
          name: 'artifacts',
          component: () => import('@/views/ArtifactsView.vue'),
          props: true,
        },
        {
          path: 'result',
          name: 'result',
          component: () => import('@/views/ResultView.vue'),
          props: true,
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})