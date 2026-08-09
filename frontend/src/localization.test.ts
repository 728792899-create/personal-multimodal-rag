import { describe, expect, it } from 'vitest'

import {
  localizedErrorMessage,
  localizedIndexStage,
  localizedParserProfile,
  localizedProvider,
  localizedQueryRewriter,
  localizedSourceType,
  localizedStatus,
  localizedSystemText,
} from './localization'

describe('中文界面语义映射', () => {
  it('maps common service statuses, indexing stages, and source types', () => {
    expect(localizedStatus('queued')).toBe('排队中')
    expect(localizedStatus('succeeded')).toBe('已完成')
    expect(localizedIndexStage('enrich_modalities')).toBe('多模态增强')
    expect(localizedSourceType('local_directory')).toBe('本地目录')
    expect(localizedSourceType('url_list')).toBe('URL 列表')
    expect(localizedStatus('not_checked')).toBe('未检查')
    expect(localizedStatus('in_progress')).toBe('处理中')
    expect(localizedParserProfile('raganything_worker')).toBe('高级解析工作进程')
    expect(localizedProvider('openai_responses')).toBe('OpenAI 响应服务')
    expect(localizedProvider('openai_compatible_chat')).toBe('兼容 OpenAI 的对话服务')
    expect(localizedProvider('sentence_transformers')).toBe('句向量模型')
    expect(localizedProvider('pgvector')).toBe('pgvector 向量库')
    expect(localizedProvider('chroma')).toBe('Chroma 向量库')
    expect(localizedQueryRewriter('off')).toBe('未启用')
  })

  it('does not surface known English service errors verbatim', () => {
    expect(localizedErrorMessage('Rate limit exceeded', '请求失败')).toBe('请求过于频繁，请稍后重试。')
    expect(localizedErrorMessage('provider unavailable', '请求失败')).toBe('服务暂时不可用，请稍后重试。')
    expect(localizedSystemText('回答 provider 未返回正文', '请求失败')).toBe('回答 服务提供方 未返回正文')
  })

  it('uses the Chinese fallback for an unknown English detail', () => {
    expect(localizedErrorMessage('unexpected upstream explosion', '操作失败，请重试。')).toBe('操作失败，请重试。')
  })
})
