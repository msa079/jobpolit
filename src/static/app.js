"use strict";
const $ = (id) => document.getElementById(id);
const state = {user:null, csrf_token:"", conversations:[], thread_id:null, messages:[], profile:null,
  busy:false, auth_mode:"login", dialog:null, menu:null, view:0};
let toast_timer;
const icon = (name) => {const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.classList.add("icon");const use=document.createElementNS(svg.namespaceURI,"use");use.setAttribute("href",`#i-${name}`);svg.append(use);return svg;};
function toast(message){$("toast").textContent=message;$("toast").hidden=false;clearTimeout(toast_timer);toast_timer=setTimeout(()=>$("toast").hidden=true,4000);}
async function api(path, options={}){
  const response=await fetch(path,{credentials:"same-origin",...options,headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf_token,...options.headers}});
  const data=await response.json().catch(()=>({error:"服务返回异常，请稍后重试。"}));
  if(!response.ok){if(response.status===401 && !path.includes("/auth/login")) show_auth();const error=new Error(data.error||"请求未完成，请重试。");error.status=response.status;throw error;}
  return data;
}
function set_auth_mode(mode){
  state.auth_mode=mode;const register=mode==="register";
  $("login-tab").classList.toggle("active",!register);$("register-tab").classList.toggle("active",register);
  $("login-tab").setAttribute("aria-selected",String(!register));$("register-tab").setAttribute("aria-selected",String(register));
  $("auth-title").textContent=register?"开启你的求职工作台":"欢迎回来";
  $("auth-subtitle").textContent=register?"创建账号，保存简历和每一段求职思路。":"登录账号，继续你的求职对话。";
  $("auth-submit").textContent=register?"创建账号并进入 →":"登录工作台 →";
  $("confirm-field").hidden=!register;$("confirm-password").required=register;
  $("password").autocomplete=register?"new-password":"current-password";$("password").minLength=register?8:1;
  $("password").placeholder=register?"至少8个字符":"输入密码";
  $("auth-error").hidden=true;
  $("auth-switch-copy").replaceChildren(document.createTextNode(register?"已经有账号？":"还没有账号？"));
  const button=document.createElement("button");button.className="text-button";button.textContent=register?"直接登录":"创建一个";
  button.addEventListener("click",()=>set_auth_mode(register?"login":"register"));$("auth-switch-copy").append(button);
}
function show_auth(){
  state.user=null;state.csrf_token="";state.thread_id=null;state.profile=null;state.messages=[];state.conversations=[];state.view++;
  $("workspace").hidden=true;$("auth-screen").hidden=false;$("boot").hidden=true;$("password").value="";$("confirm-password").value="";
  if($("conversation-dialog").open)$("conversation-dialog").close();close_resume();
}
async function enter(data){
  state.user=data.user;state.csrf_token=data.csrf_token;$("account-name").textContent=data.user.username;
  $("user-avatar").textContent=Array.from(data.user.username)[0].toUpperCase();
  $("auth-screen").hidden=true;$("workspace").hidden=false;$("boot").hidden=true;$("password").value="";$("confirm-password").value="";
  const sidebar_open=window.innerWidth>600;set_sidebar(sidebar_open);
  const results=await Promise.all([api("/api/conversations"),api("/api/profile")]);
  state.conversations=results[0].conversations;state.profile=results[1];render_conversations();render_profile();new_view();
}
function set_sidebar(open){$("workspace").classList.toggle("sidebar-collapsed",!open);$("expand-sidebar").hidden=open;$("sidebar-shade").hidden=!open||window.innerWidth>600;}
function close_menus(){document.querySelectorAll(".conversation-menu").forEach((menu)=>menu.remove());state.menu=null;}
function render_conversations(){
  const list=$("conversation-list");list.replaceChildren();const query=$("conversation-search").value.trim().toLocaleLowerCase();
  const conversations=state.conversations.filter(item=>item.title.toLocaleLowerCase().includes(query));
  $("conversation-count").textContent=String(state.conversations.length);
  if(!conversations.length){const text=document.createElement("p");text.className="sidebar-empty";text.textContent=query?"没有找到相关会话":"还没有会话，从一个问题开始吧。";list.append(text);return;}
  let previous_group="";
  for(const item of conversations){
    const date=new Date(item.updated_at);const today=new Date();const days=Math.floor((new Date(today.getFullYear(),today.getMonth(),today.getDate())-new Date(date.getFullYear(),date.getMonth(),date.getDate()))/86400000);
    const group=days===0?"今天":days===1?"昨天":days<7?"最近 7 天":"更早";
    if(group!==previous_group){const label=document.createElement("div");label.className="history-group";label.textContent=group;list.append(label);previous_group=group;}
    const row=document.createElement("div");row.className="conversation-item";row.classList.toggle("active",item.thread_id===state.thread_id);
    const open=document.createElement("button");open.className="conversation-open";open.title=item.title;open.setAttribute("aria-label",`打开会话：${item.title}`);open.append(icon("chat"));const title=document.createElement("span");title.textContent=item.title;open.append(title);
    open.addEventListener("click",()=>select_conversation(item.thread_id).catch(error=>toast(error.message)));
    const more=document.createElement("button");more.className="icon-button more-button";more.setAttribute("aria-label",`会话操作：${item.title}`);more.append(icon("more"));
    more.addEventListener("click",(event)=>{event.stopPropagation();const was_open=state.menu===item.thread_id;close_menus();if(was_open)return;state.menu=item.thread_id;const menu=document.createElement("div");menu.className="conversation-menu";
      for(const [action,label,symbol] of [["rename","重命名","edit"],["delete","删除会话","trash"]]){const button=document.createElement("button");button.className=action==="delete"?"delete-action":"";button.append(icon(symbol),document.createTextNode(label));button.addEventListener("click",()=>{close_menus();open_dialog(action,item);});menu.append(button);}row.append(menu);});
    row.append(open,more);list.append(row);
  }
}
async function refresh_conversations(){const result=await api("/api/conversations");state.conversations=result.conversations;render_conversations();const current=state.conversations.find(item=>item.thread_id===state.thread_id);$("thread-title").textContent=current?current.title:"新会话";}
function new_view(){
  if(state.busy){toast("请等当前回答完成后再新建会话。");return;}
  state.thread_id=null;state.messages=[];state.view++;$("thread-title").textContent="新会话";$("message").value="";render_messages();render_conversations();update_composer();
  if(window.innerWidth<=600)set_sidebar(false);$("message").focus();
}
async function select_conversation(thread_id){
  if(state.busy){toast("请等当前回答完成后再切换会话。");return;}
  const view=++state.view;const result=await api(`/api/conversations/${thread_id}/messages`);if(view!==state.view)return;
  state.thread_id=thread_id;state.messages=result.messages;$("thread-title").textContent=result.conversation.title;
  $("message").value="";render_messages();render_conversations();if(window.innerWidth<=600)set_sidebar(false);update_composer();
}
// 仅用DOM构造少量Markdown，不把用户/模型文本作为HTML插入。
function inline(parent,text){
  const regex=/(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
  let start=0;for(const match of text.matchAll(regex)){parent.append(document.createTextNode(text.slice(start,match.index)));let node;
    if(match[2]){node=document.createElement("strong");node.textContent=match[2];}
    else if(match[3]){node=document.createElement("code");node.textContent=match[3];}
    else{node=document.createElement("a");node.textContent=match[4];node.href=match[5];node.target="_blank";node.rel="noopener noreferrer";}
    parent.append(node);start=match.index+match[0].length;
  }parent.append(document.createTextNode(text.slice(start)));
}
function markdown(parent,text){
  const lines=text.split("\n");let code=null,ul=null;
  for(const line of lines){
    if(line.trim().startsWith("```")){if(code){parent.append(code);code=null;}else{code=document.createElement("pre");code.append(document.createElement("code"));}ul=null;continue;}
    if(code){code.firstChild.textContent+=line+"\n";continue;}
    if(!line.trim()){ul=null;continue;}
    if(/^\s*[-*]\s+/.test(line)){if(!ul){ul=document.createElement("ul");parent.append(ul);}const li=document.createElement("li");inline(li,line.replace(/^\s*[-*]\s+/,""));ul.append(li);continue;}
    ul=null;const node=document.createElement(/^#{1,6}\s/.test(line)?"h3":"p");inline(node,line.replace(/^#{1,6}\s+/,""));parent.append(node);
  }if(code)parent.append(code);
}
function render_messages(){
  $("empty-state").hidden=state.messages.length>0;const list=$("messages");list.replaceChildren();
  for(const item of state.messages){const row=document.createElement("article");row.className=`message ${item.role}`;
    if(item.role==="user"){const bubble=document.createElement("div");bubble.className="user-bubble";bubble.textContent=item.content;row.append(bubble);}
    else if(item.role==="assistant"){const head=document.createElement("div");head.className="assistant-head";const img=document.createElement("img");img.src="/favicon.svg";img.alt="";head.append(img,document.createTextNode("JobPolit"));const content=document.createElement("div");content.className="assistant-content";markdown(content,item.content);row.append(head,content);}
    else{row.textContent=item.content;if(item.retry){const retry=document.createElement("button");retry.textContent="重试这条消息 →";retry.addEventListener("click",()=>send_message(item.retry.message,item.retry.request_id));row.append(retry);}}
    list.append(row);
  }
  if(state.busy){const row=document.createElement("div");row.className="message assistant";const thinking=document.createElement("div");thinking.className="thinking";for(let i=0;i<3;i++){const dot=document.createElement("span");dot.className="thinking-dot";thinking.append(dot);}thinking.append(document.createTextNode("正在梳理思路…"));row.append(thinking);list.append(row);}
  requestAnimationFrame(()=>{$("chat-scroll").scrollTop=$("chat-scroll").scrollHeight;});
}
function update_composer(){const has_text=Boolean($("message").value.trim());$("send-message").disabled=state.busy||!has_text;$("message").disabled=state.busy;$("new-chat").disabled=state.busy;$("composer-mode").textContent=state.busy?"正在思考":"JobPolit";}
function new_id(){return crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random().toString(36).slice(2,15)}`;}
async function send_message(message,request_id=null){
  if(state.busy||!message.trim())return;message=message.trim();const user=state.user;if(!user)return;
  state.busy=true;update_composer();const id=request_id||new_id();let thread_id=state.thread_id;
  state.messages=state.messages.filter(item=>item.role!=="error");
  if(!request_id)state.messages.push({role:"user",content:message});$("message").value="";render_messages();
  try{
    if(!thread_id){const result=await api("/api/conversations",{method:"POST",body:"{}"});thread_id=result.conversation.thread_id;state.thread_id=thread_id;}
    await api(`/api/conversations/${thread_id}/messages`,{method:"POST",body:JSON.stringify({message,request_id:id})});
    if(state.user!==user)return;
    const result=await api(`/api/conversations/${thread_id}/messages`);state.messages=result.messages;
  }catch(error){
    if(state.user!==user)return;
    if(thread_id){try{const result=await api(`/api/conversations/${thread_id}/messages`);state.messages=result.messages;}catch{/* 保留已显示的输入 */}}
    state.messages.push({role:"error",content:error.message,retry:{message,request_id:id}});
  }finally{
    state.busy=false;if(state.user===user){try{await refresh_conversations();}catch(error){toast(error.message);}render_messages();update_composer();$("message").focus();}
  }
}
function open_resume(){
  $("resume-panel").hidden=false;$("resume-shade").hidden=window.innerWidth>=1200;$("resume-error").hidden=true;
  if(!$("resume-text").value && state.profile)$("resume-text").value=state.profile.text||"";
  update_resume_count();$("resume-text").focus();
}
function close_resume(){$("resume-panel").hidden=true;$("resume-shade").hidden=true;}
function update_resume_count(){$("resume-count").textContent=`${Array.from($("resume-text").value).length.toLocaleString()} / 30,000`;}
function render_profile(){
  const profile=state.profile?.profile||{};const ready=Boolean(state.profile?.updated_at);$("resume-status").classList.toggle("ready",ready);
  $("resume-status-text").textContent=ready?"简历已就绪":"尚未提交简历";$("sidebar-profile-status").textContent=ready?"画像已保存 · 随时更新":"提交后，匹配更有依据";
  $("resume-hint").hidden=ready;$("profile-result").hidden=!ready;$("resume-text").value=state.profile?.text||"";update_resume_count();
  const fields=$("profile-fields");fields.replaceChildren();if(!ready)return;
  $("profile-updated").textContent=new Date(state.profile.updated_at).toLocaleDateString("zh-CN",{month:"numeric",day:"numeric"})+" 更新";
  const labels={name:"姓名",education:"学历",major:"专业",graduation_year:"毕业届别",target_role:"目标岗位",city:"意向城市",skills:"专业技能",projects:"项目经历"};let count=0;
  for(const [key,label] of Object.entries(labels)){const value=profile[key];if(!value||(Array.isArray(value)&&!value.length))continue;count++;const row=document.createElement("div");row.className="profile-row";const name=document.createElement("div");name.className="profile-label";name.textContent=label;row.append(name);
    const content=document.createElement("div");content.className=key==="skills"?"profile-tags":"profile-value";
    if(key==="skills"){for(const skill of value){const tag=document.createElement("span");tag.className="profile-tag";tag.textContent=skill;content.append(tag);}}
    else{content.textContent=Array.isArray(value)?value.join("；"):value;}row.append(content);fields.append(row);
  }
  if(!count){const empty=document.createElement("p");empty.className="profile-empty";empty.textContent="尚未提取到明确的个人信息，请补充技能、经历和求职方向后重新提交。";fields.append(empty);}
}
function open_dialog(action,item){
  state.dialog={action,item};$("dialog-error").hidden=true;const deleting=action==="delete";
  $("dialog-title").textContent=deleting?"删除这段会话？":"重命名会话";$("dialog-description").textContent=deleting?`“${item.title}”的聊天记录将被删除，无法恢复。`:"取一个方便下次找到的名字。";
  $("rename-title").hidden=deleting;$("rename-label").hidden=deleting;$("rename-title").value=item.title;$("rename-title").required=!deleting;
  $("confirm-dialog").textContent=deleting?"删除会话":"保存";$("confirm-dialog").classList.toggle("danger",deleting);$("conversation-dialog").showModal();if(!deleting)$("rename-title").select();
}
$("login-tab").addEventListener("click",()=>set_auth_mode("login"));$("register-tab").addEventListener("click",()=>set_auth_mode("register"));
$("show-password").addEventListener("click",()=>{const show=$("password").type==="password";$("password").type=show?"text":"password";$("show-password").textContent=show?"隐藏":"显示";$("show-password").setAttribute("aria-label",show?"隐藏密码":"显示密码");});
$("auth-form").addEventListener("submit",async(event)=>{event.preventDefault();$("auth-error").hidden=true;
  if(state.auth_mode==="register" && $("password").value!==$("confirm-password").value){$("auth-error").textContent="两次输入的密码不一致。";$("auth-error").hidden=false;return;}
  $("auth-submit").disabled=true;try{const data=await api(`/api/auth/${state.auth_mode}`,{method:"POST",body:JSON.stringify({username:$("username").value,password:$("password").value})});await enter(data);}catch(error){$("auth-error").textContent=error.message;$("auth-error").hidden=false;}finally{$("auth-submit").disabled=false;}});
$("logout").addEventListener("click",async()=>{if(state.busy){toast("请等当前回答完成后再退出。");return;}try{await api("/api/auth/logout",{method:"POST",body:"{}"});show_auth();set_auth_mode("login");}catch(error){toast(error.message);}});
$("new-chat").addEventListener("click",new_view);$("collapse-sidebar").addEventListener("click",()=>set_sidebar(false));$("expand-sidebar").addEventListener("click",()=>set_sidebar(true));$("sidebar-shade").addEventListener("click",()=>set_sidebar(false));
$("conversation-search").addEventListener("input",render_conversations);document.addEventListener("click",close_menus);
for(const id of ["open-resume","sidebar-resume","welcome-resume","hint-resume"])$(id).addEventListener("click",open_resume);
$("close-resume").addEventListener("click",close_resume);$("resume-shade").addEventListener("click",close_resume);$("resume-text").addEventListener("input",update_resume_count);
$("resume-form").addEventListener("submit",async(event)=>{event.preventDefault();const user=state.user;const text=$("resume-text").value;$("resume-error").hidden=true;$("submit-resume").disabled=true;$("submit-resume").textContent="正在提取画像…";
  try{const result=await api("/api/profile",{method:"POST",body:JSON.stringify({text})});if(state.user!==user)return;state.profile=result;render_profile();toast("简历画像已保存，接下来可以分析岗位了。");}
  catch(error){if(state.user!==user)return;$("resume-error").textContent=error.message;$("resume-error").hidden=false;}
  finally{$("submit-resume").disabled=false;$("submit-resume").replaceChildren(icon("doc"),document.createTextNode("提取并保存画像"));}});
$("chat-form").addEventListener("submit",event=>{event.preventDefault();send_message($("message").value);});$("message").addEventListener("input",update_composer);
$("message").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!state.busy)send_message($("message").value);}});
document.querySelectorAll("[data-suggestion]").forEach(button=>button.addEventListener("click",()=>{$("message").value=button.dataset.suggestion;update_composer();$("message").focus();}));
for(const id of ["close-dialog","cancel-dialog"])$(id).addEventListener("click",()=>$("conversation-dialog").close());
$("conversation-action-form").addEventListener("submit",async event=>{event.preventDefault();const {action,item}=state.dialog;$("confirm-dialog").disabled=true;$("dialog-error").hidden=true;
  try{await api(`/api/conversations/${item.thread_id}`,{method:action==="delete"?"DELETE":"PATCH",body:JSON.stringify({title:$("rename-title").value})});$("conversation-dialog").close();
    if(action==="delete"&&state.thread_id===item.thread_id)new_view();await refresh_conversations();toast(action==="delete"?"会话已删除":"会话标题已更新");}
  catch(error){$("dialog-error").textContent=error.message;$("dialog-error").hidden=false;}finally{$("confirm-dialog").disabled=false;}});
document.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"&&state.user){event.preventDefault();new_view();}if(event.key==="Escape"){close_menus();close_resume();}});
window.addEventListener("resize",()=>{$("resume-shade").hidden=$("resume-panel").hidden||window.innerWidth>=1200;$("sidebar-shade").hidden=$("workspace").classList.contains("sidebar-collapsed")||window.innerWidth>600;});
async function boot(){
  $("boot-retry").hidden=true;set_auth_mode("login");try{const health=await api("/api/health");$("demo-label").hidden=!health.demo;await enter(await api("/api/auth/me"));}
  catch(error){if(error.status===401){show_auth();}else{$("boot").hidden=false;$("workspace").hidden=true;$("auth-screen").hidden=true;$("boot").querySelector("span").textContent=error.message||"暂时连接不到服务。";$("boot-retry").hidden=false;}}
}
$("boot-retry").addEventListener("click",boot);boot();
