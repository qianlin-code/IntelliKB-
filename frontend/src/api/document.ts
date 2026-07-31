import request from './request'
import { get, del } from './request'
import type { ApiResponse, DocumentInfo, DocumentUploadResponse, ChunkInfo } from '@/types'

export function uploadDocumentApi(kbId: number, file: File): Promise<ApiResponse<DocumentUploadResponse>> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('kb_id', String(kbId))
  return request.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function listDocumentsApi(kbId: number, page = 1, pageSize = 50) {
  return get<{ items: DocumentInfo[]; total: number; page: number; page_size: number }>(
    '/documents',
    { kb_id: kbId, page, page_size: pageSize }
  )
}

export function getDocumentApi(docId: number) {
  return get<DocumentInfo>(`/documents/${docId}`)
}

export function deleteDocumentApi(docId: number) {
  return del(`/documents/${docId}`)
}

export function getChunksApi(docId: number) {
  return get<{ chunks: ChunkInfo[]; total: number }>(`/documents/${docId}/chunks`)
}
