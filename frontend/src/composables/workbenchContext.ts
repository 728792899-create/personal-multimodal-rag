import { inject, type InjectionKey } from 'vue'

import type { Workbench } from './useWorkbench'


export const workbenchKey: InjectionKey<Workbench> = Symbol('workbench')

export function useWorkbenchContext(): Workbench {
  const workbench = inject(workbenchKey)
  if (!workbench) throw new Error('Workbench context is unavailable')
  return workbench
}
