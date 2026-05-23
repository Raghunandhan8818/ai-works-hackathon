import Sidebar from '@/components/dashboard/Sidebar'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen" style={{ background: '#F8F7F4' }}>
      <Sidebar />
      <div className="flex-1 flex flex-col" style={{ marginLeft: 240 }}>
        {children}
      </div>
    </div>
  )
}
