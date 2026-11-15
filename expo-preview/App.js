import React,{useEffect,useState} from 'react';
import {Linking,ActivityIndicator,AccessibilityInfo,Animated,Switch,View,Text,Image,Pressable,ScrollView,TextInput,Modal,SafeAreaView,StyleSheet} from 'react-native';
import * as Location from 'expo-location';
import MapView,{Marker} from 'react-native-maps';
import {people} from './people';
const tabs=['Discover','Second You','Matches','Settings'];
const good=people.filter(p=>p.interests.filter(x=>['Music','Design'].includes(x)).length*2+(p.goal==='Someone to explore with'?1:0)>=3);
function facts(p) {
 const careers = [['Graphic designer','BFA in Graphic Design'],['Trail guide','BS in Environmental Science'],['Film editor','BA in Film Studies'],['Product designer','BFA in Design'],['Software engineer','BS in Computer Science'],['Illustrator','BA in Fine Arts'],['Event producer','BA in Communications'],['Researcher','MSc in Biology'],['Architect','Master of Architecture']];
 return careers[p.id < 3 ? p.id : 3 + (p.id-3)%6];
}
function MatchActivity({stage}) {
 const pulse=React.useRef(new Animated.Value(0)).current;
 const [reduce,reduceMotion]=useState(true),[second,lightSecond]=useState(false);
 useEffect(()=>{let alive=true;AccessibilityInfo.isReduceMotionEnabled().then(v=>{if(alive)reduceMotion(v)});const sub=AccessibilityInfo.addEventListener('reduceMotionChanged',reduceMotion);return()=>{alive=false;sub.remove()}},[]);
 useEffect(()=>{
   pulse.setValue(0);lightSecond(false);
   if(stage==='detect'&&!reduce){
     const loop=Animated.loop(Animated.timing(pulse,{toValue:1,duration:1500,useNativeDriver:true}));
     loop.start();return ()=>loop.stop();
   }
   const timer=setTimeout(()=>lightSecond(true),reduce?0:800);return ()=>clearTimeout(timer);
 },[stage,reduce,pulse]);
 const accent='#9c294f',detect=stage==='detect';
 return <View accessible accessibilityLabel={detect?'Detecting people nearby':'Comparing interests and dating preferences'} style={[s.row,{minHeight:98,backgroundColor:'#fff4f5'}]}>
   <View style={{width:68,height:68,alignItems:'center',justifyContent:'center',gap:5}}>
     {detect?<><View style={{position:'absolute',width:65,height:65,borderRadius:33,borderWidth:1,borderColor:'#e8bbc7'}}/>
       <Animated.View style={{position:'absolute',width:36,height:36,borderRadius:18,borderWidth:2,borderColor:accent,transform:[{scale:pulse.interpolate({inputRange:[0,1],outputRange:[0.9,1.8]})}],opacity:pulse.interpolate({inputRange:[0,1],outputRange:[0.8,0.1]})}}/>
       <View style={{backgroundColor:accent,width:13,height:13,borderRadius:8}}/>
       {[[10,20],[48,11],[45,49]].map(([left,top])=><View key={left} style={{position:'absolute',left,top,width:5,height:5,borderRadius:3,backgroundColor:accent}}/>)}</>:
       ['✦','♥'].map((icon,i)=><Text key={icon} style={{fontSize:16,color:i===0||second?accent:'#cbbec3'}}>{icon} ── ●</Text>)}
   </View>
   <View style={{flex:1,gap:3}}><Text style={s.bold}>{detect?'Detecting nearby':'Comparing profiles'}</Text>
    <Text style={{color:detect?'#645960':accent}}>{detect?'Finding people open to date…':'Shared interests'}</Text>
    {!detect&&<Text style={{color:second?accent:'#81777b'}}>Dating preferences</Text>}
   </View></View>;
}
function AgentChat({person,close}){
 const topic=person.interests.find(x=>['Music','Design'].includes(x))||person.interests[0];
 const plan=topic==='Music'?'browse a record shop and each pick a song':topic==='Design'?'visit a small exhibition and pick a favorite piece':'meet for coffee and trade local recommendations';
 const turns=[
  ['First chat','What would be a good way for Elena to get to know '+person.name+'?',person.name+' lists '+person.interests.join(' and ')+'. I’d ask what got them interested in '+topic+'.'],
  ['Future talk','Elena wants someone to explore with. What does '+person.name+' hope to find?',person.name+' chose “'+person.goal+'.” They could talk about what that looks like in everyday life.'],
  ['Plan a date','How about suggesting they '+plan+' together?','Let’s offer that idea and leave the time and place for them to choose.']
 ];
 return <SafeAreaView style={{flex:1,backgroundColor:'#19121f'}}><ScrollView contentContainerStyle={{padding:18,gap:12}}>
 <Pressable onPress={close}><Text style={{color:'#ffadd6'}}>‹ Matches</Text></Pressable><Avatar p={person}/><Text style={{color:'white',fontSize:24,fontWeight:'700'}}>Match with {person.name}</Text><Text style={{color:'#cbbfcf'}}>Profile-based demo conversation</Text>
 {turns.map(([topic,a,b])=><View key={topic} style={{gap:9}}><Text style={{color:'#ffa5d4'}}>{topic}</Text>{[a,b].map((line,i)=><View key={i} style={{alignSelf:i?'flex-start':'flex-end',maxWidth:'88%',padding:13,borderRadius:16,backgroundColor:i?'#352b3d':'#53324e'}}><Text style={{color:'#ffb3d8',fontWeight:'bold',marginBottom:5}}>{i?person.name:'Elena'}’s agent</Text><Text style={{color:'white'}}>{line}</Text></View>)}</View>)}
 </ScrollView></SafeAreaView>;
}
function Chemistry({person,matched,onHi,onClose}) {
 const shared=person.interests.filter(x=>['Music','Design'].includes(x));
 const aligned=person.goal==='Someone to explore with';
 const percent=Math.round(52+30*shared.length/Math.max(2,person.interests.length)+(aligned?18:0));
 const panel={backgroundColor:'#32253c',padding:20,borderRadius:22,gap:13}, white={color:'white'};
 return <SafeAreaView style={{flex:1,backgroundColor:'#19121f'}}><ScrollView contentContainerStyle={{padding:18,gap:14}}>
 <View style={s.bar}><Text style={white}>Second You found someone</Text><Pressable onPress={onClose}><Text style={{color:'#ffaad4',padding:6}}>Close</Text></Pressable></View>
 <View style={panel}><Text style={[s.h,white,{fontSize:38}]}>{percent}% chemistry</Text><View style={{flexDirection:'row',justifyContent:'center',alignItems:'center',gap:12}}>
 <View style={{width:76,height:76,borderRadius:38,borderWidth:2,borderColor:'#ff98cd',backgroundColor:'#624761',alignItems:'center',justifyContent:'center'}}><Text style={white}>You</Text></View><Avatar p={person} size={76}/></View>
 <Text style={[white,{fontSize:23,fontWeight:'bold'}]}>{person.name}</Text><Text style={white}>{facts(person).join(' · ')}</Text><Text style={white}>{person.interests.join(' · ')}</Text>
 <Pressable onPress={onHi} style={{padding:14,alignItems:'center',backgroundColor:'#ff98cd',borderRadius:14}}><Text>{matched?'View match':'Say hi'}</Text></Pressable></View>
 <View style={panel}><Text style={[white,s.bold]}>Why you are matched</Text><Text style={white}>Shared interests · {shared.join(' & ')}</Text><Text style={white}>{aligned?'You’re both looking for: ':person.name+' is looking for: '}{person.goal}</Text><Text style={{color:'#c7bdce'}}>Chemistry is a preview score based on your listed interests and dating preferences.</Text></View></ScrollView></SafeAreaView>
}
function InstantMatch() {
 const [enabled,setEnabled]=useState(false),[stage,setStage]=useState('detect'),[delivery,setDelivery]=useState('');
 const session=React.useRef(null),sending=React.useRef(false),signaled=React.useRef(false);
 useEffect(()=>{
   if(!enabled)return;
   const analyzing=setTimeout(()=>setStage('analyze'),2000);
   const ready=setTimeout(()=>setStage('ready'),4000);
   return ()=>{clearTimeout(analyzing);clearTimeout(ready)};
 },[enabled]);
 useEffect(()=>{
   if(enabled&&stage==='ready'&&!signaled.current){
     signaled.current=true;
     signal('accept');
   }
 },[enabled,stage]);
 async function signal(answer){
   if(sending.current)return;
   sending.current=true;setDelivery('Sending…');
   const base='https://vexo-match.onrender.com/api/signal';
   try{
     for(let attempt=0;attempt<2;attempt++){
       if(!session.current){
         const name='Elena-'+Math.random().toString(36).slice(2,8);
         const join=await fetch(base+'/join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
         if(!join.ok)throw Error();
         session.current=(await join.json()).token;
       }
       if(answer==='accept'){
         const roster=await fetch(base+'/members',{headers:{Authorization:'Bearer '+session.current},cache:'no-store'});
         if(roster.status===401){session.current=null;continue}
         if(!roster.ok)throw Error();
         if(!(await roster.json()).members.some(m=>m.online!==false&&m.name.toLowerCase()==='kgen')){
           setDelivery('Kagen’s receiver is offline. Connect it as kgen, then run Instant matching again.');return;
         }
       }
       const response=await fetch(base,{method:'POST' ,headers:{'Content-Type':'application/json',Authorization:'Bearer '+session.current},body:JSON.stringify({to:'kgen',answer})});
       if(response.status===401){session.current=null;continue}
       if(!response.ok)throw Error();
       setDelivery(answer==='accept'?'Green signal sent to Kagen’s bracelet receiver.':'Sent reject to kgen');if(answer==='reject')setStage('passed');return;
     }
     throw Error();
   }catch{setDelivery('Delivery unconfirmed for kgen')}finally{sending.current=false}
 }
 return <View style={{gap:10}}><View style={s.bar}><Text style={s.bold}>Instant matching</Text><Switch value={enabled} disabled={sending.current} onValueChange={v=>{signaled.current=false;setStage('detect');setDelivery('');setEnabled(v)}}/></View>
 {enabled&&(stage==='passed'?<Text>No suggested profiles nearby yet.</Text>:stage!=='ready'?<MatchActivity stage={stage}/>:<View style={{backgroundColor:'white',borderRadius:16,padding:16,gap:8}}>
 <View style={s.bar}><Text>Suggested for you</Text><Text accessibilityLabel="Demo distance, 5 meters" style={s.bold}>5 m</Text></View><View style={s.row}><Avatar p={{photo:require('./assets/portraits/kgen.jpg')}} size={58}/><Text style={s.h}>Kagen</Text></View>
 <Text>Architect</Text><Text>B.Arch. in Architecture</Text><Text>Photography · Live music</Text><Text>I shoot film on weekends. Pick a neighborhood and I’ll find us a coffee spot.</Text>
 <View style={s.bar}>
 <Pressable disabled={delivery==='Sending…'} onPress={()=>signal('reject')}><Text style={s.action}>Pass</Text></Pressable></View>{!!delivery&&<Text>{delivery}</Text>}</View>)}</View>
}
const compatibleIds=new Set(good.map(person=>person.id));
const groups=Array.from({length:6},(_,i)=>people.filter(p=>p.id%6===i));
function Avatar({p,size=46}){return <Image source={p.photo} style={{width:size,height:size,borderRadius:size/2,borderWidth:2,borderColor:'white'}}/>}
function Debrief({date,review,save,close,plan}){
 const idea=review.idea??review.turns.map(t=>t.note).join('\n\n');
 const card={padding:18,borderRadius:18,backgroundColor:'#30243e',gap:12};
 const white={color:'white'}, heading={color:'white',fontWeight:'700',fontSize:17};
 const update=patch=>save({...review,...patch,done:false});
 return <SafeAreaView style={{flex:1,backgroundColor:'#1c1526'}}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{padding:20,gap:18}}>
 <Pressable onPress={close}><Text style={{color:'#ffadd6'}}>‹ Matches</Text></Pressable><Text style={heading}>Analyze Date</Text>
 <View style={s.bar}><Avatar p={date.person}/><Text style={white}>{date.person.name} · {date.place}</Text></View>
 <View style={card}><Text style={heading}>Share your idea</Text><TextInput multiline value={idea} onChangeText={idea=>update({idea})} accessibilityLabel="Share your idea" placeholder="How did the date feel?" placeholderTextColor="#c4b6ca" style={{color:'white',minHeight:72,textAlignVertical:'top'}}/></View>
 <View style={card}><Text style={heading}>Rate your date</Text>{[0,5].map(start=><View key={start} style={{flexDirection:'row',gap:6}}>{Array.from({length:5},(_,i)=>start+i+1).map(n=><Pressable key={n} accessibilityRole="button" accessibilityState={{selected:n===review.rating}} onPress={()=>update({rating:n})} style={{backgroundColor:n===review.rating?'#ffadd6':'#493c52',flex:1,minHeight:44,justifyContent:'center',alignItems:'center',borderRadius:22}}><Text style={{color:n===review.rating?'black':'white'}}>{n}</Text></Pressable>)}</View>)}</View>
 <Pressable disabled={!review.rating} onPress={()=>save({...review,done:true})} style={{backgroundColor:'#ffadd6',opacity:review.rating?1:0.5,padding:14,borderRadius:14,alignItems:'center'}}><Text style={s.bold}>Summarize Date</Text></Pressable>
 {review.done&&<View style={card}><Text style={heading}>Date summary</Text><Text style={white}>Your rating · {review.rating}/10</Text>{!!idea.trim()&&<Text style={white}>You wrote: “{idea}”</Text>}<Text style={white}>{review.rating>=8?'If you’d like to meet again, suggest a second date.':review.rating>=5?'Give yourself time before deciding.':'You can leave it here if the connection didn’t feel right.'}</Text>{review.rating>=6&&<Pressable onPress={plan}><Text style={{color:'#ffadd6'}}>Plan it</Text></Pressable>}</View>}
 </ScrollView></SafeAreaView>
}
export default function App(){
 const [chat,setChat]=useState(null);
 const [reviews,setReviews]=useState({}),[date,setDate]=useState(null);
 const [sample]=useState(()=>({id:'sample',person:people[3],when:new Date(Date.now()-86400000),place:'Record fair · Demo date'}));
 const emptyReview={turns:[],rating:0,intent:'Unsure',done:false};
 const [action,setAction]=useState(null),[plans,setPlans]=useState({});
 function plan(person,key=String(person.id)){setAction({type:'date',person,key})}
 const datePlan=action?.type==='date'?plans[action.key]:null;
 useEffect(()=>{
   if(action?.type!=='date'||datePlan)return;
   const timer=setTimeout(()=>{
     const now=new Date(), reserved=Object.values(plans);
     for(let offset=0;offset<=reserved.length+1;offset++){
       for(const hour of [18,19,20]){
         const when=new Date(now);when.setDate(when.getDate()+offset);when.setHours(hour,0,0,0);
         if(when-now<7200000||reserved.some(plan=>Math.abs(when-plan.when)<7200000))continue;
         setPlans(old=>({...old,[action.key]:{when,person:action.person,confirmed:false}}));return;
       }
     }
   },2400);
   return ()=>clearTimeout(timer);
 },[action,datePlan,plans]);
 function roomCoordinate(index){
   const angle=index*Math.PI/3;
   return {latitude:anchor.latitude+16*Math.cos(angle)/111000,longitude:anchor.longitude+17*Math.sin(angle)/(111000*Math.cos(anchor.latitude*Math.PI/180))};
 }
 const [tab,T]=useState('Discover'),[fix,F]=useState(null),[anchor,A]=useState(null),[msg,M]=useState('Finding your location…'),[open,O]=useState(true),[list,L]=useState(null),[detail,D]=useState(null),[matches,S]=useState([1,3]),[note,N]=useState('I enjoy music, design, and walking home after a concert.'),[partner,setPartner]=useState("Someone curious and kind who asks follow-up questions, follows through on plans, and can laugh with me when we miss the opening act."),[ideal,setIdeal]=useState('An early set at a small jazz club, then a walk somewhere quiet so we can talk about our favorite song.');
 useEffect(()=>{if(!open)return;let active=true,sub; (async()=>{if((await Location.requestForegroundPermissionsAsync()).status!=='granted'){if(active)M('Allow location to see the map.');return}sub=await Location.watchPositionAsync({accuracy:Location.Accuracy.BestForNavigation,distanceInterval:1},({coords})=>{if(active){F(coords);A(old=>old||coords)}});if(!active)sub.remove()})().catch(()=>active&&M('Location unavailable.'));return()=>{active=false;sub?.remove()}},[open]);
 const button=(label,fn)=><Pressable onPress={fn}><Text style={s.action}>{label}</Text></Pressable>;
 const history=[sample,...Object.entries(plans).filter(([,p])=>p.confirmed&&p.when<=new Date()).map(([id,p])=>({...p,id,place:'Ruby Wine, Potrero Hill'}))].sort((a,b)=>b.when-a.when);
 const row=p=><Pressable key={p.id} onPress={()=>{L(null);D(p)}} style={s.row}><Avatar p={p}/><View><Text style={s.bold}>{p.name}</Text><Text>{p.interests.join(' · ')}</Text></View></Pressable>;
 return <SafeAreaView style={s.bg}><ScrollView contentContainerStyle={{padding:18,gap:14}}><Text style={s.brand}>✿  OPEN DATE</Text>
 {tab==='Discover'?<><View style={s.bar}><Text style={s.h}>Around you</Text>{button(open?'Leave':'Enter',()=>O(!open))}</View>{open&&<>{fix&&anchor?<MapView style={s.map} showsUserLocation initialRegion={{latitude:fix.latitude,longitude:fix.longitude,latitudeDelta:.00055,longitudeDelta:.00055}}>{groups.map((g,i)=>{const first=g.find(p=>compatibleIds.has(p.id))||g[0];return <Marker key={i} coordinate={roomCoordinate(i)} onPress={()=>L(g)}><View style={{padding:3}}><Avatar p={first} size={40}/>{compatibleIds.has(first.id)&&<Text accessibilityLabel="High compatibility" style={s.heart}>♥</Text>}<Text style={s.count}>{g.length}</Text></View></Marker>})}</MapView>:<Text>{msg}</Text>}
 <Text>120 open · 180 demo attendees</Text><InstantMatch/><View style={s.bar}><Text style={s.h}>Open to date</Text>{button('120 ›',()=>L(people))}</View><ScrollView horizontal>{people.slice(0,20).map(p=><Pressable key={p.id} onPress={()=>D(p)} style={{alignItems:'center',marginRight:12}}><Avatar p={p}/><Text>{p.name}</Text></Pressable>)}</ScrollView><View style={s.bar}><Text style={s.h}>High compatibility</Text>{button(good.length+' ›',()=>L(good))}</View>{good.slice(0,12).map(row)}</>}</>:tab==='Matches'?<><Text style={s.h}>Matches</Text>{matches.map(i=>{const person=people[i];const dates=history.filter(d=>d.person.id===i);return <View key={i} style={{backgroundColor:'white',borderRadius:18,padding:14,gap:12}}>
 <Pressable style={s.row} onPress={()=>setChat(person)}><Avatar p={person}/><View><Text style={s.bold}>{person.name}</Text><Text>{person.interests.join(' · ')}</Text></View></Pressable>
 <View style={s.bar}>{button('Chat',()=>setChat(person))}{button('⌖  Find',()=>setAction({type:'find',person}))}{dates.length?dates.map(d=><Pressable key={d.id} onPress={()=>setDate(d)}><Text style={s.action}>Analyze date{dates.length>1?' · '+d.when.toLocaleDateString():''}</Text></Pressable>):button('Arrange date',()=>plan(person))}</View></View>})}</>:tab==='Settings'?<><Text style={s.h}>Settings</Text>{button('My profile',()=>T('Second You'))}{button('Location and notification permissions',()=>Linking.openSettings())}</>:<><Text style={s.h}>Second You</Text>
 <View style={s.profileCard}><Text style={s.h}>About Me</Text><Text style={s.bold}>Elena</Text><Text>I design album covers and spend Sundays digging through used records.</Text>
 <Text>Work · Graphic designer</Text><Text>Education · BFA in Visual Communication</Text><Text>Interests · Design and Music</Text><Text style={s.bold}>In my own words</Text>
 <TextInput multiline accessibilityLabel="In my own words" style={s.profileInput} value={note} onChangeText={N}/></View>
 <View style={s.profileCard}><Text style={s.h}>My Ideal Date</Text><Text style={s.bold}>Who I’d like to meet</Text><TextInput multiline accessibilityLabel="Who I’d like to meet" style={s.profileInput} value={partner} onChangeText={setPartner}/><Text>Looking for · Someone to explore with</Text><Text style={s.bold}>My kind of first date</Text>
 <TextInput multiline accessibilityLabel="My kind of first date" style={s.profileInput} value={ideal} onChangeText={setIdeal}/></View></>}
 </ScrollView><View style={s.nav}>{tabs.map(t=><Pressable key={t} onPress={()=>T(t)}><Text style={{fontWeight:tab===t?'800':'400',color:'#852a45'}}>{t}</Text></Pressable>)}</View>
 <Modal visible={!!(detail||list||chat||action||date)} onRequestClose={()=>{D(null);L(null);setChat(null);setAction(null);setDate(null)}}>{date?<Debrief date={date} review={reviews[date.id]||emptyReview} close={()=>setDate(null)} save={r=>setReviews(old=>({...old,[date.id]:r}))} plan={()=>{plan(date.person,date.id+'-next');setDate(null)}}/>:action?<SafeAreaView style={s.bg}><ScrollView contentContainerStyle={{padding:22,gap:16}}>
 {button('Close',()=>setAction(null))}<Avatar p={action.person}/><Text style={s.h}>{action.type==='date'?'Arrange date with ':'Find '}{action.person.name}</Text>
 {action.type==='find'?(anchor&&open?<><Text>Demo location</Text><MapView style={s.map} showsUserLocation initialRegion={{...anchor,latitudeDelta:.00055,longitudeDelta:.00055}}><Marker coordinate={roomCoordinate(action.person.id%6)} title={action.person.name}><Avatar p={action.person}/></Marker></MapView></>:<Text>Enter the room and allow location to view the map.</Text>):<View style={{padding:22,gap:15,backgroundColor:'#31263f',borderRadius:20}}>
 {datePlan?<><Text style={{color:'#ffadd6'}}>{datePlan.confirmed?'Date set':'First date'}</Text>
 <Text style={{fontFamily:'Georgia',fontSize:30,color:'white'}}>{datePlan.when.toLocaleDateString(undefined,{weekday:'long'})} · {datePlan.when.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'})}</Text>
 <Text style={{color:'white'}}>{datePlan.when.toLocaleDateString(undefined,{month:'long',day:'numeric',year:'numeric'})}</Text>
 <Text style={{color:'white'}}>Ruby Wine, Potrero Hill · For two</Text>
 <Text style={{color:'white'}}>Suggested departure · {new Date(datePlan.when-1200000).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'})}</Text>
 <Pressable disabled={datePlan.confirmed} style={{backgroundColor:'#ffadd6',padding:12,borderRadius:12,alignItems:'center'}} onPress={()=>setPlans(old=>({...old,[action.key]:{...datePlan,confirmed:true}}))}><Text>{datePlan.confirmed?'Confirmed by you':'Confirm'}</Text></Pressable>
 <Text style={{color:'#dbd2e0'}}>Demo itinerary · No bookings or invitations.</Text></>:<><ActivityIndicator color="#ffadd6"/><Text style={{color:'white'}}>Finding a time for two…</Text></>}</View>}

 </ScrollView></SafeAreaView>:chat?<AgentChat person={chat} close={()=>setChat(null)}/>:detail && compatibleIds.has(detail.id)?<Chemistry person={detail} matched={matches.includes(detail.id)} onClose={()=>D(null)} onHi={()=>{S(old=>[...new Set([...old,detail.id])]);D(null);T('Matches')}}/>:<SafeAreaView style={s.bg}><ScrollView contentContainerStyle={{padding:22,gap:16}}>{button('Close',()=>{D(null);L(null)})}{detail?<><Avatar p={detail} size={90}/><Text style={s.h}>{detail.name}</Text><Text>{detail.goal}</Text><Text>{facts(detail).join(" · ")}</Text><Text>{detail.interests.join(' · ')}</Text>{button(matches.includes(detail.id)?'View match':'Like '+detail.name,()=>{S(old=>[...new Set([...old,detail.id])]);D(null);T('Matches')})}</>:list?.map(row)}</ScrollView></SafeAreaView>}</Modal></SafeAreaView>
}
const s=StyleSheet.create({profileCard:{backgroundColor:'white',padding:16,borderRadius:18,gap:10},profileInput:{fontSize:16,lineHeight:22,color:'#3b192b'},bg:{flex:1,backgroundColor:'#fbf7f2'},h:{fontFamily:'Georgia',fontSize:26,color:'#3b192b'},brand:{fontSize:15,letterSpacing:2,fontWeight:'700',color:'#80233f'},bar:{flexDirection:'row',alignItems:'center',justifyContent:'space-between'},nav:{flexDirection:'row',justifyContent:'space-around',paddingVertical:14},map:{height:320,borderRadius:18},action:{padding:8,color:'#862c49',fontWeight:'600'},row:{flexDirection:'row',alignItems:'center',gap:12,backgroundColor:'white',padding:12,borderRadius:14},bold:{fontWeight:'700'},input:{backgroundColor:'white',minHeight:140,padding:12,borderRadius:12},heart:{position:'absolute',right:1,top:0,width:17,height:17,lineHeight:17,textAlign:'center',fontSize:13,fontWeight:'bold',color:'#d52864',backgroundColor:'white',borderRadius:9,overflow:'hidden'},count:{position:'absolute',bottom:0,right:0,color:'white',backgroundColor:'black',borderRadius:8,overflow:'hidden',fontSize:10,paddingHorizontal:3}})
