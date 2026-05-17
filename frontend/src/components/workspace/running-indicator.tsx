"use client";

interface RunningIndicatorProps {
  className?: string;
}

export function RunningIndicator({ className }: RunningIndicatorProps) {
  return (
    <span
      className={`inline-flex items-center justify-center bg-background ${className ?? ""}`}
      style={{
        width: 16,        // 容器宽度
        height: 16,       // 容器高度
        position: "relative",
        flexShrink: 0,
        zIndex: 10,       // 确保能遮挡文字
      }}
    >
      {/* 铅笔主体 */}
      <span
        style={{
          position: "absolute",
          bottom: 2,        // 距离底部1px（笔尖位置）
          left: 4,          // 水平居中偏左
          width: 4,         // 笔身宽度
          height: 14,        // 笔身高度
          background: "#333",  // 笔身颜色（深灰）
          borderRadius: 0.1,
          transformOrigin: "bottom center",  // 旋转中心：笔尖
          animation: "pencil-swing 0.5s ease-in-out infinite alternate",
        }}
      >
        {/* 笔尖（CSS三角形） */}
        <span
          style={{
            position: "absolute",
            bottom: -1,     // 笔尖向下延伸2px
            left: 0,
            width: 0,
            height: 1,
            borderLeft: "1.5px solid transparent",
            borderRight: "1.5px solid transparent",
            borderTop: "2px solid #111",  // 笔尖颜色（黑）
          }}
        />
        {/* 橡皮（白底黑边） */}
        <span
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: 3,       // 与笔身同宽
            height: 2.5,    // 橡皮高度
            background: "#fff",  // 白色
            border: "0.5px solid #222",
            borderBottom: "none",
            borderRadius: "0.5px 0.5px 0 0",
            boxSizing: "border-box",
          }}
        />
      </span>
      {/* 书写线条 */}
      <span
        style={{
          position: "absolute",
          bottom: -1,        // 线条在底部
          left: 2,
          width: 9,         // 线条长度
          height: 2,        // 线条粗细
          background: "#222",
          borderRadius: 0.5,
          animation: "write-line 0.5s ease-in-out infinite alternate",
        }}
      />
      <style>{`
        /* 铅笔摆动动画：绕笔尖左右摆动 */
        @keyframes pencil-swing {
          0% { transform: rotate(-10deg); }
          100% { transform: rotate(10deg); }
        }
        /* 线条跟随动画：左右平移+透明度变化 */
        @keyframes write-line {
          0% { transform: translateX(-1px); opacity: 0.5; }
          100% { transform: translateX(1px); opacity: 1; }
        }
      `}</style>
    </span>
  );
}
