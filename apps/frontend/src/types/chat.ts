export interface Source {
   id: string
   title: string
   content: string
   url?: string
   page?: string
   score?: number
}

export interface Message {
   id: string
   role: 'user' | 'assistant'
   content: string
   sources?: Source[]
   timestamp: string
}

export interface ChatSession {
   id: string
   title: string
   messages: Message[]
   createdAt: string
}
