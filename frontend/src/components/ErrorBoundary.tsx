import { Component, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
          <div className="card p-8 max-w-md text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-red-100">
              <span className="text-2xl">!</span>
            </div>
            <h2 className="text-lg font-semibold text-slate-950">页面加载异常</h2>
            <p className="mt-2 text-sm text-slate-500">{this.state.error.message}</p>
            <button
              className="btn-primary mt-6"
              onClick={() => {
                this.setState({ error: null })
                window.location.reload()
              }}
            >
              刷新页面
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}